import sys
import threading
import faulthandler
from pathlib import Path

faulthandler.enable()

def dump_and_exit():
    sys.stderr.write("\n\n=== TIMEOUT: dumping stacks (all threads) ===\n")
    faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
    sys.stderr.write("\n=== END DUMP ===\n")
    raise SystemExit(2)

t = threading.Timer(20.0, dump_and_exit)
t.daemon = True
t.start()

def log(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()

log("STEP 0: importing orchestrator.phase1 ...")
from orchestrator.phase1 import start_case, collect_document
log("STEP 1: imported OK")

log("STEP 2: start_case() ...")
cid = start_case()
log(f"STEP 3: start_case OK cid={cid}")

proposta = "tests/fixtures/andersonsantos.pdf"
cnh = "tests/fixtures/CNH DIGITAL.pdf"

log(f"STEP 4: collect proposta {proposta} ...")
collect_document(cid, proposta, document_type="proposta_daycoval")
log("STEP 5: proposta OK")

log(f"STEP 6: collect cnh {cnh} ...")
collect_document(cid, cnh, document_type="cnh")
log("STEP 7: cnh OK")

print(cid)
