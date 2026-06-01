import requests, os, glob
from .config import BARK_TOKENS

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(BASE_DIR, 'results')
ORDERS_DIR = os.path.join(BASE_DIR, 'orders')

def send_bark(title, body):
    """Send Bark push to all registered devices"""
    api_url = "http://www.ggsuper.com.cn/push/api/v1/sendMsg3_New.php"
    all_ok = True
    for i, token in enumerate(BARK_TOKENS):
        payload = {
            'token': token,
            'title': title,
            'msg': body,
            'url': '',
            'issecure': 0,
            'sender': '量化选股系统',
        }
        try:
            resp = requests.post(api_url, json=payload,
                               headers={'Content-Type': 'application/json'}, timeout=15)
            print(f"[BARK-{i+1}] HTTP {resp.status_code}, Response: {resp.text[:300]}")
            if resp.status_code == 200:
                try:
                    result = resp.json()
                    if str(result.get('code')) == '80000000':
                        print(f"[BARK-{i+1}] Server confirms: message sent successfully")
                        continue
                    else:
                        print(f"[BARK-{i+1}] Server error: {result.get('msg', 'unknown')}")
                except Exception:
                    if '成功' in resp.text:
                        continue
            all_ok = False
        except Exception as e:
            print(f"[BARK-{i+1}] Error: {e}")
            all_ok = False
    return all_ok

def send_from_newbie_file():
    """从newbie_instruction_card.py预生成的bark_simple文件读取并发送"""
    today_str = datetime.now().strftime('%Y%m%d')
    bark_file = os.path.join(BASE_DIR, 'orders', f'bark_simple_{today_str}.txt')
    if not os.path.exists(bark_file):
        print(f"[BARK] No newbie bark file: {bark_file}")
        return None

    with open(bark_file, 'r', encoding='utf-8') as f:
        content = f.read()

    title = None
    body_lines = []
    for line in content.split('\n'):
        if line.startswith('TITLE: ') and title is None:
            title = line[7:].strip()
        elif title is not None:
            body_lines.append(line)

    if not title:
        print("[BARK] Invalid bark_simple format")
        return None

    return title, '\n'.join(body_lines).strip()


