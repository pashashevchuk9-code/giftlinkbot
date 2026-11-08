from pathlib import Path
p = Path("roles.py")
data = p.read_bytes()

# Add WORKER_COMMANDS after USER_COMMANDS
old = (
    b'USER_COMMANDS: list[tuple[str, str]] = [\r\n'
    b'    ("/start", "\xd0\xb3\xd0\xbb\xd0\xb0\xd0\xb2\xd0\xbd\xd0\xbe\xd0\xb5 \xd0\xbc\xd0\xb5\xd0\xbd\xd1\x8e"),\r\n'
    b'    ("/profile", "\xd0\xbc\xd0\xbe\xd0\xb9 \xd0\xbf\xd1\x80\xd0\xbe\xd1\x84\xd0\xb8\xd0\xbb\xd1\x8c"),\r\n'
    b'    ("/deals", "\xd0\xbc\xd0\xbe\xd0\xb8 \xd0\xbf\xd1\x80\xd0\xb5\xd0\xb4\xd0\xbb\xd0\xbe\xd0\xb6\xd0\xb5\xd0\xbd\xd0\xb8\xd1\x8f"),\r\n'
    b'    ("/history", "\xd0\xb8\xd1\x81\xd1\x82\xd0\xbe\xd1\x80\xd0\xb8\xd1\x8f \xd1\x81\xd0\xb4\xd0\xb5\xd0\xbb\xd0\xbe\xd0\xba"),\r\n'
    b'    ("/rules", "\xd0\xbf\xd1\x80\xd0\xb0\xd0\xb2\xd0\xb8\xd0\xbb\xd0\xb0 \xd0\xbe\xd0\xb1\xd0\xbc\xd0\xb5\xd0\xbd\xd0\xb0"),\r\n'
    b'    ("/comand", "\xd1\x81\xd0\xbf\xd0\xb8\xd1\x81\xd0\xbe\xd0\xba \xd0\xba\xd0\xbe\xd0\xbc\xd0\xb0\xd0\xbd\xd0\xb4"),\r\n'
    b']\r\n'
)
new = old + b'''
WORKER_EXTRA_COMMANDS: list[tuple[str, str]] = [
    ("/workerpanel", "\xd0\xbf\xd0\xb0\xd0\xbd\xd0\xb5\xd0\xbb\xd1\x8c \xd1\x81\xd0\xbe\xd1\x82\xd1\x80\xd1\x83\xd0\xb4\xd0\xbd\xd0\xb8\xd0\xba\xd0\xb0"),
    ("/workerinfo", "\xd0\xb8\xd0\xbd\xd1\x84\xd0\xbe\xd1\x80\xd0\xbc\xd0\xb0\xd1\x86\xd0\xb8\xd1\x8f \xd0\xbe \xd1\x80\xd0\xbe\xd0\xbb\xd0\xb8"),
    ("/workerstats", "\xd1\x81\xd1\x82\xd0\xb0\xd1\x82\xd0\xb8\xd1\x81\xd1\x82\xd0\xb8\xd0\xba\xd0\xb0 \xd1\x81\xd0\xbe\xd1\x82\xd1\x80\xd1\x83\xd0\xb4\xd0\xbd\xd0\xb8\xd0\xba\xd0\xb0"),
    ("/workerhistory", "\xd0\xb8\xd1\x81\xd1\x82\xd0\xbe\xd1\x80\xd0\xb8\xd1\x8f \xd0\xb0\xd0\xba\xd1\x82\xd0\xb8\xd0\xb2\xd0\xbd\xd0\xbe\xd1\x81\xd1\x82\xd0\xb8"),
    ("/workerhelp", "\xd0\xbf\xd0\xbe\xd0\xbc\xd0\xbe\xd1\x89\xd1\x8c \xd1\x81\xd0\xbe\xd1\x82\xd1\x80\xd1\x83\xd0\xb4\xd0\xbd\xd0\xb8\xd0\xba\xd1\x83"),
]

WORKER_COMMANDS: list[tuple[str, str]] = _dedupe(USER_COMMANDS + WORKER_EXTRA_COMMANDS)
'''
assert old in data, "USER_COMMANDS not found"
data = data.replace(old, new, 1)

# Update commands_for_role
old2 = b'    if role in {Role.ADMIN, Role.IVAN}:\r\n        return _dedupe(USER_COMMANDS + ADMIN_COMMANDS)\r\n    return list(USER_COMMANDS)\r\n'
new2 = b'    if role is Role.WORKER:\r\n        return list(WORKER_COMMANDS)\r\n    if role in {Role.ADMIN, Role.IVAN}:\r\n        return _dedupe(USER_COMMANDS + ADMIN_COMMANDS)\r\n    return list(USER_COMMANDS)\r\n'
assert old2 in data, "commands_for_role not found"
data = data.replace(old2, new2, 1)

# Update command_sections
old3 = b'    if role in {Role.ADMIN, Role.IVAN}:\r\n        return [("USER / WORKER", USER_COMMANDS), ("ADMIN / IVAN", ADMIN_COMMANDS)]\r\n    return [("USER / WORKER", USER_COMMANDS)]\r\n'
new3 = b'    if role is Role.WORKER:\r\n        return [("USER", USER_COMMANDS), ("WORKER", WORKER_EXTRA_COMMANDS)]\r\n    if role in {Role.ADMIN, Role.IVAN}:\r\n        return [("USER / WORKER", USER_COMMANDS), ("ADMIN / IVAN", ADMIN_COMMANDS)]\r\n    return [("USER / WORKER", USER_COMMANDS)]\r\n'
assert old3 in data, "command_sections not found"
data = data.replace(old3, new3, 1)

p.write_bytes(data)
print("done")
import ast
ast.parse(p.read_text(encoding="utf-8"))
print("SYNTAX OK")
