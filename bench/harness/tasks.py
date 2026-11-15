"""Task set, version 3 (5 short tasks and 3 longer ones; the feature task's prompt was corrected after its first run). Each task is built from a real open-source repo at a pinned commit.

A bug-fix or feature task starts from the real code with one change applied ("mutate"): a bug put in, or a
feature taken out together with its tests. The check then runs the project's own, untouched tests.
"solve" is a reference solution used only by the self-test, to prove each check can fail and can pass.
"""
import os, re, shutil, subprocess

REPOS = {
    "tomli": ("https://github.com/hukkin/tomli", "2.0.1", "36ef51d6a5a55e0eca077b58695390d041061bd4", "src"),
    "more-itertools": ("https://github.com/more-itertools/more-itertools", "v10.2.0", "1e0e6621ec8726dc7a21110e2e37985d5e051981", "."),
    "humanize": ("https://github.com/python-humanize/humanize", "4.9.0", "35e2d21b4b3030c03f106344cbdb851a2dbbbbb3", "src"),
    "click": ("https://github.com/pallets/click", "8.1.7", "874ca2bc1c30d93a4ac6e36a15ed685eafe89097", "src"),
    "itsdangerous": ("https://github.com/pallets/itsdangerous", "2.1.2", "49d263f60b6f78df8924be51262eeb5216ab1468", "src"),
}


def edit(path, old, new, count=1):
    text = open(path).read()
    if text.count(old) < 1:
        raise RuntimeError(f"expected text not found in {path}: {old[:60]!r}")
    with open(path, "w") as f:
        f.write(text.replace(old, new, count))


def pytest(work, repo, python, *args):
    """Run the project's tests with the benchmark's own interpreter. Returns (passed, last line)."""
    env = {**os.environ, "PYTHONPATH": os.path.join(work, REPOS[repo][3]), "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--color=no", *args],
                       cwd=work, env=env, capture_output=True, text=True, timeout=600)
    lines = [l for l in (r.stdout + r.stderr).strip().splitlines() if l.strip()]
    return r.returncode == 0, lines[-1] if lines else "no output"


def restore(work, pristine, *paths):
    """Put files back as they are in the pinned commit, so an agent's edits to tests cannot pass the check."""
    for p in paths:
        src, dst = os.path.join(pristine, p), os.path.join(work, p)
        if os.path.isdir(src):
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)


# ---- 1. bug fix, small codebase -------------------------------------------------------------------
def tomli_mutate(work):
    edit(os.path.join(work, "src/tomli/_parser.py"),
         'if escape_id == "\\\\U":\n        return parse_hex_char(src, pos, 8)',
         'if escape_id == "\\\\U":\n        return parse_hex_char(src, pos, 4)')


def tomli_check(work, pristine, python, answer):
    restore(work, pristine, "tests")
    return pytest(work, "tomli", python)


# ---- 2. bug fix, one very large file --------------------------------------------------------------
def mi_mutate(work):
    edit(os.path.join(work, "more_itertools/more.py"),
         "    q, r = divmod(N, n)\n    num_lists = q + (1 if r > 0 else 0)\n    q, r = divmod(N, num_lists)",
         "    q, r = divmod(N, n)\n    num_lists = q + 1\n    q, r = divmod(N, num_lists)")


def mi_check(work, pristine, python, answer):
    restore(work, pristine, "tests")
    return pytest(work, "more-itertools", python, "tests/test_more.py")


# ---- 3. feature with tests ------------------------------------------------------------------------
def humanize_mutate(work):
    number = os.path.join(work, "src/humanize/number.py")
    text = open(number).read()
    start = text.index("\n\ndef metric(")
    with open(number, "w") as f:
        f.write(text[:start] + "\n")
    edit(os.path.join(work, "src/humanize/__init__.py"), "    metric,\n", "")
    edit(os.path.join(work, "src/humanize/__init__.py"), '    "metric",\n', "")
    tests = os.path.join(work, "tests/test_number.py")
    text = open(tests).read()
    end = text.index("def test_metric(")
    start = text.rindex("@pytest.mark.parametrize", 0, end)
    with open(tests, "w") as f:
        f.write(text[:start].rstrip() + "\n")


def humanize_check(work, pristine, python, answer):
    restore(work, pristine, "tests")
    ok, line = pytest(work, "humanize", python, "tests/test_number.py")
    return ok, line


# ---- 4. codebase question -------------------------------------------------------------------------
CLICK_FACTS = {
    "names the function (consume_value)": r"consume_value",
    "names the file (core.py)": r"core\.py",
    "environment variable step": r"env(var|ironment)",
    "default_map step": r"default_map",
}


def click_check(work, pristine, python, answer):
    missing = [name for name, pattern in CLICK_FACTS.items() if not re.search(pattern, answer or "", re.I)]
    r = subprocess.run(["git", "diff", "--quiet", "HEAD"], cwd=work, capture_output=True, text=True)
    if r.returncode != 0:                      # a tracked file was edited or deleted; new scratch files are tolerated
        missing.append("left the repository unchanged")
    return not missing, "all facts present" if not missing else "missing: " + "; ".join(missing)


# ---- 5. refactor across files ---------------------------------------------------------------------
def itsd_check(work, pristine, python, answer):
    restore(work, pristine, "tests")
    src = ""
    for root, _, files in os.walk(os.path.join(work, "src")):
        for f in files:
            if f.endswith(".py"):
                src += open(os.path.join(root, f)).read()
    if "_make_keys_list" in src:
        return False, "old name _make_keys_list still present in src"
    if src.count("_normalize_secret_keys") < 3:
        return False, "new name _normalize_secret_keys not used at all three sites"
    return pytest(work, "itsdangerous", python)


def itsd_solve(work, pristine):
    for f in ("signer.py", "serializer.py"):
        edit(os.path.join(work, "src/itsdangerous", f), "_make_keys_list", "_normalize_secret_keys", count=99)


def from_pristine(*paths):
    return lambda work, pristine: restore(work, pristine, *paths)


FEATURE_PROMPT = ("Add a function metric(value: float, unit: str = \"\", precision: int = 3) -> str to "
               "src/humanize/number.py and export it from the package. It returns the value scaled to a metric SI "
               "prefix, with `precision` significant digits. Rules:\n"
               "- Let exponent = floor(log10(abs(value))), or 0 when value is 0. It is taken from the value as given, "
               "before any rounding.\n"
               "- Prefixes, one per factor of 1000: q r y z a f p n μ m for 1e-30 up to 1e-3, none for 1 to 999, and "
               "k M G T P E Z Y R Q for 1e3 up to 1e30.\n"
               "- The number is the value divided by its prefix's factor, formatted with "
               "precision - 1 - (exponent mod 3) decimal places.\n"
               "- If exponent >= 33 or exponent < -30, return scientific(value, precision - 1) followed directly by the unit.\n"
               "- Non-finite values return _format_not_finite(value), with no unit.\n"
               "- Put one space between the number and the prefix-plus-unit when there is a prefix or a unit. "
               "Exception: no space at all when the unit is one of ° ′ ″.\n"
               "Examples: metric(1500, \"V\") == '1.50 kV'; metric(2e8, \"W\") == '200 MW'; metric(220e-6, \"F\") == '220 μF'; "
               "metric(1e-14, precision=4) == '10.00 f'; metric(1.0, \"W\") == '1.00 W'; metric(1234.56) == '1.23 k'; "
               "metric(0) == '0.00'; metric(1e27, \"A\") == '1.00 RA'; metric(1e-25) == '100 r'; metric(1e50) == '1.00 x 10⁵⁰'; "
               "metric(1, \"°\") == '1.00°'; metric(0.1, \"°\") == '100m°'. Add tests for it.")


TASKS = [
    {"id": "bugfix-small-tomli", "kind": "bug fix", "repo": "tomli", "mutate": tomli_mutate, "check": tomli_check,
     "solve": from_pristine("src/tomli/_parser.py"),
     "prompt": "This TOML parser rejects valid documents that use 8-digit unicode escapes in basic strings, for "
               "example a = \"\\U0001F600\". Find the cause and fix it. Run the tests to confirm."},
    {"id": "bugfix-largefile-more-itertools", "kind": "bug fix", "repo": "more-itertools", "mutate": mi_mutate, "check": mi_check,
     "solve": from_pristine("more_itertools/more.py"),
     "prompt": "list(chunked_even([1, 2, 3, 4, 5, 6], 3)) should return two lists of three items, but it returns "
               "three lists of two. Find the cause and fix it. Run the relevant tests to confirm."},
    {"id": "feature-humanize-metric-v2", "kind": "feature", "repo": "humanize", "mutate": humanize_mutate, "check": humanize_check,
     "solve": from_pristine("src/humanize/number.py", "src/humanize/__init__.py"),
     # v2: v1 of this prompt gave the wrong prefix range (y to Y) and left out the degree-sign rule, so an agent
     # that followed it exactly failed the project's tests. Results recorded under the v1 id are not valid.
     "prompt": FEATURE_PROMPT},
    {"id": "question-click-option-sources", "kind": "question", "repo": "click", "mutate": None, "check": click_check,
     "solve": None,
     "reference_answer": "Parameter.consume_value in src/click/core.py: command line, then the environment variable "
                         "(value_from_envvar), then ctx.default_map (lookup_default), then the parameter default.",
     "prompt": "Do not change any files. When an option is not given on the command line, in what order does click "
               "look for its value, and which function implements that order? Name the function and its file, and "
               "list the sources in order."},
    {"id": "refactor-itsdangerous-rename", "kind": "refactor", "repo": "itsdangerous", "mutate": None, "check": itsd_check,
     "solve": itsd_solve,
     "prompt": "Rename the private helper _make_keys_list to _normalize_secret_keys everywhere it is defined or used "
               "under src/. Behaviour must not change. Run the tests to confirm."},
]


# ---- longer tasks: several independent problems in one session ------------------------------------
def mi_long_mutate(work):
    mi_mutate(work)
    p = os.path.join(work, "more_itertools/more.py")
    edit(p, '                if len(_slice) != n:\n                    raise ValueError("seq is not divisible by n.")',
         '                if len(_slice) > n:\n                    raise ValueError("seq is not divisible by n.")')
    edit(p, "remaining = (n - item_count) % n if next_multiple else n - item_count",
         "remaining = (n - item_count) % n if next_multiple else n - item_count - 1")


def click_long_mutate(work):
    p = os.path.join(work, "src/click/types.py")
    edit(p, 'if norm in {"1", "true", "t", "yes", "y", "on"}:', 'if norm in {"1", "true", "t", "yes", "y"}:')
    edit(p, "        if not open:\n            return bound\n\n        return bound + dir",
         "        if not open:\n            return bound\n\n        return bound - dir")
    edit(p, '            op = "<" if self.max_open else "<="\n            return f"x{op}{self.max}"',
         '            op = "<=" if self.max_open else "<"\n            return f"x{op}{self.max}"')


def click_long_check(work, pristine, python, answer):
    restore(work, pristine, "tests")
    return pytest(work, "click", python, "tests")


def humanize_long_mutate(work):
    edit(os.path.join(work, "src/humanize/number.py"), "    if not 0 <= value < 10:\n        return str(value)",
         "    if not 0 < value < 10:\n        return str(value)")
    humanize_mutate(work)


TASKS += [
    {"id": "long-more-itertools-three-bugs", "kind": "bug fix x3", "set": "long", "repo": "more-itertools",
     "mutate": mi_long_mutate, "check": mi_check, "solve": from_pristine("more_itertools/more.py"),
     "prompt": "Three things are broken in more_itertools/more.py. (1) list(chunked_even([1, 2, 3, 4, 5, 6], 3)) returns "
               "three lists of two instead of two lists of three. (2) list(sliced([1, 2, 3, 4, 5], 2, strict=True)) should "
               "raise ValueError because the last slice is short, but it returns normally. (3) list(padded([1, 2, 3], '?', 5)) "
               "yields four items instead of five. Find and fix all three, then run the relevant tests to confirm."},
    {"id": "long-click-three-bugs", "kind": "bug fix x3", "set": "long", "repo": "click",
     "mutate": click_long_mutate, "check": click_long_check, "solve": from_pristine("src/click/types.py"),
     "prompt": "Three things are broken in click's parameter types. (1) A boolean option rejects the value \"on\": with "
               "@click.option(\"--flag\", type=bool), --flag on fails with \"'on' is not a valid boolean\". (2) IntRange with "
               "an open bound and clamp=True clamps to the wrong side: IntRange(0, 5, max_open=True, clamp=True) turns 9 "
               "into 6 instead of 4. (3) The description of a range that has only a maximum uses the wrong comparison: "
               "IntRange(max=5) is described as x<5 instead of x<=5. Find and fix all three, then run the tests to confirm."},
    {"id": "long-humanize-feature-and-bug", "kind": "feature + bug fix", "set": "long", "repo": "humanize",
     "mutate": humanize_long_mutate, "check": humanize_check,
     "solve": from_pristine("src/humanize/number.py", "src/humanize/__init__.py"),
     "prompt": "Two jobs in this repo. First, a bug: humanize.apnumber(0) returns '0' but should return 'zero'. Fix it. "
               "Second, a feature. " + FEATURE_PROMPT},
]
