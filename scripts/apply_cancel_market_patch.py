#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import re
ROOT = Path(__file__).resolve().parents[1]

def patch_jobs_py():
    p = ROOT / "app/api/jobs.py"
    s = p.read_text(encoding="utf-8")
    old = s
    if "import signal" not in s:
        s = s.replace("import subprocess\n", "import subprocess\nimport signal\n") if "import subprocess\n" in s else "import signal\n" + s
    s = s.replace("UPDATE job_execution SET message=:msg, updated_at=NOW() WHERE id=:id", "UPDATE job_execution SET pid=:pid, message=:msg, updated_at=NOW() WHERE id=:id")
    s = s.replace("{\"id\": job_id, \"msg\": f\"started pid={proc.pid}, total={total}\"}", "{\"id\": job_id, \"pid\": proc.pid, \"msg\": f\"started pid={proc.pid}, total={total}\"}")
    if "@router.post(\"/executions/{job_id}/cancel\")" not in s:
        endpoint = ""
        endpoint += '\n'
        endpoint += '@router.post("/executions/{job_id}/cancel")\n'
        endpoint += 'def cancel_execution(job_id: int, db: Session = Depends(get_db)):\n'
        endpoint += '    if not _table_exists(db, "job_execution"):\n'
        endpoint += '        return {"ok": False, "message": "job_execution table not found"}\n'
        endpoint += '    row = db.execute(text("SELECT id, status, pid FROM job_execution WHERE id=:job_id"), {"job_id": job_id}).mappings().first()\n'
        endpoint += '    if not row:\n'
        endpoint += '        return {"ok": False, "message": "job not found", "job_id": job_id}\n'
        endpoint += '    pid = row.get("pid")\n'
        endpoint += '    kill_result = "no pid"\n'
        endpoint += '    if pid:\n'
        endpoint += '        try:\n'
        endpoint += '            os.kill(int(pid), signal.SIGTERM)\n'
        endpoint += '            kill_result = f"SIGTERM sent to pid={pid}"\n'
        endpoint += '        except ProcessLookupError:\n'
        endpoint += '            kill_result = f"pid={pid} not found"\n'
        endpoint += '        except PermissionError:\n'
        endpoint += '            kill_result = f"permission denied for pid={pid}"\n'
        endpoint += '        except Exception as exc:\n'
        endpoint += '            kill_result = f"kill error: {exc}"\n'
        endpoint += '    db.execute(text("""UPDATE job_execution SET status=\'cancelled\', cancel_requested_at=NOW(), message=CONCAT(IFNULL(message,\'\'), \' | cancelled by user; \', :kill_result), finished_at=NOW(), updated_at=NOW() WHERE id=:job_id"""), {"job_id": job_id, "kill_result": kill_result})\n'
        endpoint += '    if _table_exists(db, "job_task_item"):\n'
        endpoint += '        db.execute(text("""UPDATE job_task_item SET status=\'cancelled\', last_error=\'cancelled by user\', finished_at=NOW(), updated_at=NOW() WHERE job_id=:job_id AND status IN (\'pending\',\'running\')"""), {"job_id": job_id})\n'
        endpoint += '    db.commit()\n'
        endpoint += '    return {"ok": True, "job_id": job_id, "status": "cancelled", "kill_result": kill_result}\n'
        endpoint += '\n'
        marker = "@router.get(\"/executions/{job_id}/logs\")"
        s = s.replace(marker, endpoint + "\n" + marker) if marker in s else s + endpoint
    if "if m == \"sh60\"" not in s:
        s = s.replace("if m == \"sz\":\n        return f\"{col} LIKE \\\'sz.%\\\'\"", "if m == \"sz\":\n        return f\"{col} LIKE \\\'sz.%\\\'\"\n    if m == \"sh60\":\n        return f\"{col} LIKE \\\'sh.60%\\\'\"\n    if m == \"sh68\":\n        return f\"{col} LIKE \\\'sh.68%\\\'\"\n    if m == \"sz00\":\n        return f\"{col} LIKE \\\'sz.00%\\\'\"\n    if m == \"sz30\":\n        return f\"{col} LIKE \\\'sz.30%\\\'\"")
    if s != old:
        p.write_text(s, encoding="utf-8")
        print("OK patched app/api/jobs.py")

def patch_ui():
    opts = """<option value="sh">sh 上海</option>
                  <option value="sz">sz 深圳</option>
                  <option value="sh60">sh60 沪主板60</option>
                  <option value="sh68">sh68 科创68</option>
                  <option value="sz00">sz00 深主板00</option>
                  <option value="sz30">sz30 创业板30</option>"""
    files = ["app/static/index.html", "app/static/app.js", "app/static/jobs_actions.js", "app/static/jobs_page_bootstrap.js", "app/static/job_progress_monitor.js"]
    for name in files:
        p = ROOT / name
        if not p.exists(): continue
        s = p.read_text(encoding="utf-8")
        old = s
        s = re.sub(r"(<select[^>]*id=[\"\']jobMarket[\"\'][^>]*>)([\s\S]*?)(</select>)", lambda m: m.group(1)+"\n                  "+opts+"\n                "+m.group(3), s)
        s = s.replace("<option value="all">all 全市场</option>", "")
        s = s.replace("? $('jobMarket').value : 'all'", "? $('jobMarket').value : 'sh'")
        s = s.replace("$('jobMarket') ? $('jobMarket').value : 'all'", "$('jobMarket') ? $('jobMarket').value : 'sh'")
        if name.endswith("job_progress_monitor.js"):
            if "cancelCurrentJobBtn" not in s:
                s = s.replace("<button id="jobProgressRefreshBtn">刷新进度</button>", "<button id="jobProgressRefreshBtn">刷新进度</button><button id="cancelCurrentJobBtn" class="danger">取消当前任务</button>")
                s = s.replace("$('jobProgressRefreshBtn').onclick = refreshProgress;", "$('jobProgressRefreshBtn').onclick = refreshProgress;\n    if($('cancelCurrentJobBtn')) $('cancelCurrentJobBtn').onclick = cancelCurrentJob;")
            if "async function cancelCurrentJob" not in s:
                func = """

  async function cancelCurrentJob(){
    if(!currentJobId){ alert('没有当前任务可取消'); return; }
    if(!confirm(`确认取消当前任务？\n\n任务ID：${currentJobId}`)) return;
    const data = await postJson(`/api/jobs/executions/${currentJobId}/cancel`, {});
    if($('jobActionResult')) $('jobActionResult').textContent = JSON.stringify(data, null, 2);
    await refreshProgress();
  }
"""
                s = s.replace("  function startPolling(){", func+"\n  function startPolling(){")
        if s != old:
            p.write_text(s, encoding="utf-8")
            print("OK patched", name)

def main():
    patch_jobs_py()
    patch_ui()
    print("OK: cancel + market patch applied")

if __name__ == "__main__":
    main()
