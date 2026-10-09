"""Read-only database health view."""
from __future__ import annotations

import html

import engine
from views_core import tabs_setup


class HealthViews:
    def view_health(self, con):
        report = engine.data_health(con)
        if report["ok"]:
            summary = f"<div class='ok'><b>Book passed {report['checks']} health checks.</b> No critical integrity problems were found. {report['warning']} warning finding(s) remain.</div>"
        else:
            summary = f"<div class='critical-banner'><b>Book needs attention.</b> {report['critical']} critical finding(s) and {report['warning']} warning finding(s) were found across {report['checks']} checks.</div>"
        rows = []
        for i in report["issues"]:
            cls = "critical" if i["severity"] == "critical" else ("" if i["severity"] == "warning" else "hint")
            ex = ", ".join(html.escape(str(x)) for x in i["examples"])
            rows.append(
                f"<tr><td class='{cls}'>{html.escape(i['severity'].title())}</td>"
                f"<td><b>{html.escape(i['code'])}</b><br>{html.escape(i['message'])}</td>"
                f"<td>{i['count']}</td><td>{ex or '—'}</td></tr>"
            )
        body = "".join(rows) or "<tr><td colspan=4>No findings. The book is internally consistent against the current health rules.</td></tr>"
        return tabs_setup("/setup/health") + f"""
        {summary}
        <div class='actions'>
          <a class='btn secondary' href='/setup/health'>Run again</a>
          <a class='btn secondary' href='/backup'>Backups</a>
        </div>
        <table>
          <tr><th>Severity</th><th>Finding</th><th>Count</th><th>Examples</th></tr>
          {body}
        </table>
        """
