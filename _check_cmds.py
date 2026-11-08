import re
from pathlib import Path
all_code = ""
for f in ["handlers.py", "admin_handlers.py", "tech_handlers.py", "extra_admin.py", "worker_handlers.py", "menu_handlers.py"]:
    all_code += Path(f).read_text(encoding="utf-8")
cmds = set()
for m in re.finditer(r'Command\("([^"]+)"', all_code):
    cmds.add(m.group(1))
for m in re.finditer(r'Command\("([^"]+)",\s*"([^"]+)"\)', all_code):
    cmds.add(m.group(1))
    cmds.add(m.group(2))
print("Total:", len(cmds))
# Check which spec commands are missing
spec_cmds = {"id", "offers", "deal", "notifications", "support", "cancel", "ping", "status", "mystats", "report", "faq", "language",
    "workerpanel", "workerinfo", "workerstats", "workerhistory", "workerhelp",
    "techpanel", "health", "serverinfo", "uptime", "latency", "runtime", "performance", "traffic", "requests", "requeststats",
    "webhookinfo", "webhookcheck", "webhookstats", "updates", "updatecheck", "retryqueue", "callbackstats", "inlinecheck", "botapi",
    "dbinfo", "dbhealth", "dbstats", "dbtables", "dbsize", "dbcheck", "dberrors", "dbquery",
    "logs", "errors", "error", "errorsearch", "eventlog", "securitylog", "audit", "logstats", "clearlogs",
    "queue", "jobs", "jobstats", "scheduler", "notifications_stats", "storageinfo", "limits", "usage",
    "diagnostics", "selftest", "dbtest", "webhooktest", "inlinetest", "callbacktest", "permissiontest", "configcheck", "dependencycheck", "securitycheck", "healthreport", "reporttech",
    "stats", "users", "userscount", "dealstats", "dealsstats", "broadcast", "settings", "topusers", "newusers", "todaystats", "weekstats", "monthstats", "searchuser", "searchdeal", "exportstats", "broadcast_stats", "activity", "referrals",
    "setrole", "removerole", "roles", "roleinfo", "roleusers", "permissions", "zakrit", "open", "restart_info", "botstats", "maintenance", "backup_info", "broadcast_all", "shutdown_info", "ownerpanel",
    "antispam", "autodelete", "deletetime", "cleanbot", "offerdelete", "offerpreview", "offerstats", "offerlist", "offersearch", "offerinfo", "offerexpire", "offerpause", "offerresume", "offerlimit", "offersettings",
    "useractivity", "userdeals", "useroffers", "userrole", "userhistory", "usernote", "usernotes", "botinfo", "botmode", "maintenance_info", "broadcast_preview", "broadcast_cancel", "feature", "featurelist", "backupstatus",
    "inbox", "achievements",
    "start", "profile", "deals", "history", "rules", "comand", "whoami", "fannyteam", "help", "myoffers", "deal", "notifications", "support", "cancel", "ping", "status", "mystats", "report", "faq", "language",
}
missing = spec_cmds - cmds
print("Missing:", len(missing))
print(sorted(missing))
