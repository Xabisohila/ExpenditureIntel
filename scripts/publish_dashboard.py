import os
import shutil
import subprocess
import sys

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), '..')
SOURCE = os.path.join(PROJECT_ROOT, 'data', 'processed', 'dashboard.html')
DEST = os.path.join(PROJECT_ROOT, 'docs', 'index.html')


def run(*cmd, capture=True):
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=capture, text=True)
    if capture:
        print(result.stdout, end='')
        if result.returncode != 0:
            print(result.stderr, end='', file=sys.stderr)
    return result.returncode


def main():
    if not os.path.exists(SOURCE):
        print(f"No dashboard found at {SOURCE} -- run scripts/build_dashboard.py (or ingest_week.py) first.")
        return False

    shutil.copyfile(SOURCE, DEST)
    print(f"Copied {SOURCE} -> {DEST}")

    run('git', 'add', 'docs/index.html')
    # Compare the now-staged file against HEAD (not the working tree, which
    # `git diff` alone would use) so a brand-new untracked file on the very
    # first publish is correctly seen as "changed" rather than silently
    # skipped.
    unchanged = run('git', 'diff', '--cached', '--quiet', '--', 'docs/index.html') == 0
    if unchanged:
        print("\ndocs/index.html is unchanged from what's already committed -- nothing to publish.")
        return True

    commit_rc = run('git', 'commit', '-m', 'Publish updated dashboard\n\nCo-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>')
    if commit_rc == 0:
        print("\nCommitted. This does NOT push automatically -- run 'git push origin master' "
              "(or ask me to) to make the update live.")
    return commit_rc == 0


if __name__ == '__main__':
    main()
