"""Server-rendered, script-free local connection settings. Never render tokens."""
from html import escape


STYLE = """+:root{color-scheme:light dark;--bg:#f5f4f0;--surface:#fff;--ink:#262631;--muted:#696875;--line:#e5e3dd;--accent:#6551c6;--soft:#eeebfb;--error:#ae3f43}
@media(prefers-color-scheme:dark){:root{--bg:#17181c;--surface:#202126;--ink:#eeedf3;--muted:#aaa8b5;--line:#36363e;--accent:#b5a3ff;--soft:#332d4b;--error:#ffacac}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 "Leelawadee UI","Noto Sans Thai",Tahoma,system-ui,sans-serif}main{max-width:720px;margin:40px auto;padding:0 20px 40px}h1{font-size:28px;line-height:1.3;margin:8px 0}h2{font-size:19px;margin:0 0 12px}p{margin:8px 0 16px}.eyebrow,.muted,small{color:var(--muted)}.eyebrow{letter-spacing:.12em;font-size:12px}.card{background:var(--surface);border:1px solid var(--line);border-radius:18px;padding:24px;margin:18px 0}.badge{display:inline-block;background:var(--soft);color:var(--accent);padding:4px 12px;border-radius:20px;font-size:14px}.row{display:flex;justify-content:space-between;gap:16px;padding:10px 0;border-bottom:1px solid var(--line);flex-wrap:wrap}.row:last-child{border:0}.row strong{overflow-wrap:anywhere}button,.button{display:inline-block;border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:11px 17px;border-radius:10px;font:inherit;cursor:pointer;text-decoration:none;max-width:100%;white-space:normal}button.primary,.primary{background:var(--accent);color:var(--bg);border-color:var(--accent)}button:disabled{opacity:.55;cursor:default}a{color:var(--accent)}:focus-visible{outline:3px solid var(--accent);outline-offset:3px}label{display:block;margin:12px 0 6px}input,select{font:inherit;width:100%;padding:12px;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:9px;min-width:0}form{margin:12px 0}code{display:block;padding:14px;background:var(--bg);border-radius:9px;white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px}.error{color:var(--error)}summary{cursor:pointer;font-weight:600}details p{margin-top:14px}.actions{display:flex;gap:10px;flex-wrap:wrap}.actions form{margin:0}ul{padding-left:22px}footer{font-size:13px;color:var(--muted);margin-top:24px}@media(max-width:400px){main{margin-top:24px;padding:0 12px 24px}.card{padding:18px}.row{display:block}.row strong{display:block}}
"""


def shell(content, *, title="ตั้งค่าการเชื่อมต่อ"):
    return (f'<!doctype html><html lang="th"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{escape(title)} · Manga Thai Reader</title><style>{STYLE}</style></head>'
            f'<body><main><div class="eyebrow">MANGA THAI READER · SETTINGS</div>{content}'
            '<footer>ใช้งานเฉพาะเครื่องนี้ · ข้อมูลเข้าสู่ระบบ ChatGPT อยู่ในระบบแปลในเครื่อง</footer>'
            '</main></body></html>')


def form(action, csrf, label, fields="", primary=False):
    return (f'<form method="post" action="{action}"><input type="hidden" name="csrf" value="{csrf}">'
            f'{fields}<button type="submit" class="{"primary" if primary else ""}">{label}</button></form>')


def settings_page(record, status, models=(), catalog_error=False, message=None):
    csrf = escape(record["csrf"], quote=True)
    intro = '<h1>ตั้งค่าการเชื่อมต่อ</h1><p class="muted">เชื่อมต่อครั้งเดียว แล้วกลับไปอ่านได้เลย</p>'
    if message:
        intro += f'<p class="error" role="alert">{escape(message)}</p>'
    if not record["admin"]:
        return shell(intro + '<section class="card"><span class="badge">ยังไม่ได้อนุญาตการตั้งค่า</span>'
                     '<h2>เปิดจากส่วนขยายที่จับคู่ไว้</h2><p>ใน Settings ของส่วนขยาย กด “จัดการการเชื่อมต่อ” เพื่อเปิดหน้านี้โดยไม่ต้องกรอก admin key</p>'
                     '<p>หากยังไม่ได้จับคู่ ให้รันคำสั่งนี้ใน Terminal ของเครื่องคุณ</p>'
                     '<code>docker compose exec api python -m app.local_security pair</code>'
                     '<p>นำรหัสที่ได้ไปกรอกใน Settings ของส่วนขยาย รหัสใช้ได้ครั้งเดียวภายใน 10 นาที และใช้อนุญาตการแปลกับการจัดการการเชื่อมต่อ</p></section>'
                     '<details class="card"><summary>กู้คืนด้วย admin key เดิม</summary>'
                     '<p>สำหรับการติดตั้งเดิมที่มี key อยู่แล้ว การจับคู่แบบใหม่ไม่ต้องสร้างหรือเก็บ key นี้</p>' +
                     form('/auth/unlock', csrf, 'ปลดล็อกด้วย key เดิม',
                          '<label for="admin-key">Local admin key</label><input id="admin-key" type="password" name="key" autocomplete="off" required>') + '</details>')
    connected = bool(status.get("connected"))
    permission = bool(status.get("plan_usage_enabled"))
    model = status.get("model")
    badge = 'ตรวจการเชื่อมต่อแล้ว' if connected and permission and model else 'ตั้งค่าอีกนิดเดียว'
    body = intro + f'<section class="card"><span class="badge">{badge}</span>'
    for label, value in [('บัญชี ChatGPT', status.get('email') or ('เชื่อมต่อแล้ว' if connected else 'ยังไม่ได้เชื่อมต่อ')),
                         ('สิทธิ์ใช้แผน ChatGPT', 'อนุญาตแล้ว' if permission else 'ยังไม่ได้อนุญาต'),
                         ('โมเดลที่เลือก', model or 'ยังไม่ได้เลือก')]:
        body += f'<div class="row"><span>{label}</span><strong>{escape(str(value))}</strong></div>'
    body += '</section>'
    if not connected or not permission:
        body += '<section class="card"><h2>1. เชื่อมต่อ ChatGPT</h2><p>เข้าสู่ระบบและตรวจสอบการอนุญาตให้แอปใช้แผน ChatGPT ของคุณ</p>'
        body += form('/auth/start', csrf, 'เชื่อมต่อ ChatGPT', primary=True) + '</section>'
    else:
        body += '<section class="card"><h2>เลือกโมเดลสำหรับแปลภาพ</h2>'
        if catalog_error:
            body += '<p class="error" role="alert">โหลดรายการโมเดลไม่สำเร็จ โมเดลเดิมยังไม่ถูกเปลี่ยน</p><a class="button" href="/settings">โหลดรายการอีกครั้ง</a>'
        elif models:
            options = '<option value="" disabled' + (' selected' if not model else '') + '>เลือกโมเดล</option>'
            slugs = {item['slug'] for item in models}
            if model and model not in slugs:
                options += f'<option value="" disabled selected>โมเดลเดิมไม่อยู่ในรายการ: {escape(str(model))}</option>'
            for item in models:
                slug = escape(str(item['slug']), quote=True)
                name = escape(str(item.get('display_name') or item['slug']))
                options += f'<option value="{slug}"' + (' selected' if item['slug'] == model else '') + f'>{name}</option>'
            body += form('/auth/model', csrf, 'บันทึกโมเดล', '<label for="model">โมเดลที่บัญชีนี้ใช้ได้</label><select id="model" name="slug" required>' + options + '</select>', True)
        else:
            body += '<p>บัญชีนี้ยังไม่มีรายการโมเดลให้เลือก ลองโหลดใหม่หรือเชื่อมต่อบัญชีอีกครั้ง</p><a class="button" href="/settings">โหลดรายการใหม่</a>'
        body += '<small>เลือกโมเดลที่รองรับภาพ รายการนี้ยังไม่ยืนยันความสามารถด้านภาพหรือโควตาคงเหลือ</small></section>'
    if connected and permission and model and not catalog_error and any(item["slug"] == model for item in models):
        body += '<section class="card"><h2>กลับไปอ่านได้แล้ว</h2><p>กลับไปแท็บมังงะ เปิด Reader แล้วกด “แปลภาพที่เห็น”</p><small>การตรวจสถานะนี้ยังไม่ได้ส่งภาพไปแปล การแปลจริงอาจใช้โควตาบัญชี</small></section>'
    body += '<details class="card"><summary>ขั้นสูงและการเชื่อมต่อ</summary><p>เชื่อมต่อบัญชีเดิมอีกครั้งเมื่อสิทธิ์หมดอายุ</p>'
    body += form('/auth/reconnect', csrf, 'เชื่อมต่อบัญชีเดิมอีกครั้ง')
    body += '<details><summary>ออกจากบัญชี ChatGPT</summary><p>ระบบนี้จะหยุดใช้บัญชี ChatGPT คำแปลที่บันทึกไว้ในส่วนขยายยังอยู่</p>'
    body += form('/auth/logout', csrf, 'ยืนยันออกจากบัญชี') + '</details>'
    body += '<details><summary>ยกเลิกการจับคู่ส่วนขยาย</summary><p>ส่วนขยายนี้จะแปลและเปิดการตั้งค่าไม่ได้ ต้องจับคู่ใหม่ บัญชี ChatGPT ยังคงเชื่อมต่ออยู่</p>'
    body += form('/auth/pair/revoke', csrf, 'ยืนยันยกเลิกการจับคู่') + '</details></details>'
    return shell(body)
