"""Self-test: gira tutti i test modulo su fixtures offline N volte (default 3).
Deterministico (no rete). Esce 0 se tutti PASS in tutti i giri.
Uso: py -3.11 -X utf8 selftest.py [N]
"""
import subprocess, sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
TESTS = ["tests/test_offline.py", "tests/test_exec_dialog.py", "tests/test_page2text_progress.py",
         "tests/test_radio_select.py", "tests/test_real_offline.py", "tests/test_regression.py"]


def run_once(i):
    print(f"\n########## GIRO {i} ##########")
    allok = True
    for t in TESTS:
        p = subprocess.run([sys.executable, "-X", "utf8", t], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8")
        last = (p.stdout.strip().splitlines() or ["(no output)"])[-1]
        status = "PASS" if p.returncode == 0 else "FAIL"
        print(f"  [{status}] {t} -> {last}")
        if p.returncode != 0:
            allok = False
            print(p.stdout[-800:])
            print(p.stderr[-400:])
    return allok


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    results = [run_once(i + 1) for i in range(n)]
    ok = all(results)
    print(f"\n===== SELFTEST {sum(results)}/{n} giri PASS =====")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
