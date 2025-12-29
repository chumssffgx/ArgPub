from flask import Flask, render_template, request, redirect, url_for, jsonify
import csv
import os
import uuid
import markdown
import sys
import webview
from threading import Thread
import time

# --- 1. パス設定 (exe化と通常実行の両方に対応) ---
if getattr(sys, 'frozen', False):
    # exeで実行されている場合 (内部リソースの場所)
    template_folder = os.path.join(sys._MEIPASS, 'templates')
    static_folder = os.path.join(sys._MEIPASS, 'static')
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
    # データの保存先 (exeファイルと同じ階層)
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # 通常のPythonで実行されている場合
    app = Flask(__name__)
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- 2. CSVファイルの設定 ---
CSV_DIR = os.path.join(BASE_DIR, 'csv')
if not os.path.exists(CSV_DIR):
    os.makedirs(CSV_DIR)

SITES_CSV = os.path.join(CSV_DIR, 'sites.csv')
LOGS_CSV = os.path.join(CSV_DIR, 'logs.csv')
MEMOS_CSV = os.path.join(CSV_DIR, 'memos.csv')
RECORDS_CSV = os.path.join(CSV_DIR, 'records.csv')

SITE_FIELDS = ['id', 'name', 'url']
LOG_FIELDS = ['id', 'site_id', 'word', 'url', 'result', 'extra1', 'extra2', 'parent_id']
MEMO_FIELDS = ['id', 'site_id', 'word', 'description']
RECORD_FIELDS = ['id', 'title', 'content']

# --- 3. 共通関数 ---
def read_csv(path):
    if not os.path.exists(path): return []
    with open(path, 'r', encoding='utf-8') as f:
        return list(csv.DictReader(f))

def write_csv(path, fieldnames, rows):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def build_tree(logs, parent_id=''):
    tree = []
    for log in logs:
        if log.get('parent_id', '') == parent_id:
            children = build_tree(logs, log['id'])
            log_copy = dict(log)
            log_copy['children'] = children
            tree.append(log_copy)
    return tree

def get_all_descendant_ids(logs, parent_id):
    descendant_ids = []
    for log in logs:
        if log.get('parent_id') == parent_id:
            descendant_ids.append(log['id'])
            descendant_ids.extend(get_all_descendant_ids(logs, log['id']))
    return descendant_ids

# 初回起動時のCSV作成
for path, fields in [(SITES_CSV, SITE_FIELDS), (LOGS_CSV, LOG_FIELDS), 
                     (MEMOS_CSV, MEMO_FIELDS), (RECORDS_CSV, RECORD_FIELDS)]:
    if not os.path.exists(path): write_csv(path, fields, [])

# --- 4. Flask ルート定義 ---

@app.route('/')
def index():
    sites = read_csv(SITES_CSV)
    all_logs = read_csv(LOGS_CSV)
    target_site_id = request.args.get('site_id')
    
    site_map = {s['id']: s['name'] for s in sites}
    for log in all_logs:
        log['site_name'] = site_map.get(log['site_id'], '不明')

    if target_site_id:
        root_logs = [l for l in all_logs if l['site_id'] == target_site_id and not l.get('parent_id')]
        display_logs = []
        for root in root_logs:
            root['children'] = build_tree(all_logs, root['id'])
            display_logs.append(root)
    else:
        display_logs = build_tree(all_logs)
        
    return render_template('index.html', sites=sites, logs=display_logs, target_site_id=target_site_id)

@app.route('/log/new', methods=['GET', 'POST'])
def add_log():
    if request.method == 'POST':
        logs = read_csv(LOGS_CSV)
        logs.append({
            'id': str(uuid.uuid4()),
            'site_id': request.form.get('site_id'),
            'word': request.form.get('word'),
            'url': request.form.get('url'),
            'result': request.form.get('result'),
            'extra1': request.form.get('extra1'),
            'extra2': request.form.get('extra2'),
            'parent_id': request.form.get('parent_id', '')
        })
        write_csv(LOGS_CSV, LOG_FIELDS, logs)
        next_url = request.form.get('next_url')
        return redirect(next_url if next_url and next_url != 'None' else url_for('index'))
    
    sites = read_csv(SITES_CSV)
    return render_template('add_log.html', sites=sites, 
                         initial_site_id=request.args.get('initial_site_id', ''), 
                         initial_word=request.args.get('initial_word', ''), 
                         initial_result=request.args.get('initial_result', ''),
                         parent_id=request.args.get('parent_id', ''),
                         next_url=request.referrer)

@app.route('/log/edit/<log_id>', methods=['GET', 'POST'])
def edit_log(log_id):
    logs = read_csv(LOGS_CSV)
    log = next((l for l in logs if l['id'] == log_id), None)
    if request.method == 'POST':
        if log:
            log.update({
                'word': request.form.get('word'),
                'url': request.form.get('url'),
                'result': request.form.get('result'),
                'extra1': request.form.get('extra1'),
                'extra2': request.form.get('extra2')
            })
            write_csv(LOGS_CSV, LOG_FIELDS, logs)
        next_url = request.form.get('next_url')
        return redirect(next_url if next_url and next_url != 'None' else url_for('index'))
    
    sites = read_csv(SITES_CSV)
    site_name = next((s['name'] for s in sites if s['id'] == log['site_id']), "不明")
    return render_template('edit_log.html', log=log, site_name=site_name, next_url=request.referrer)

@app.route('/log/delete/<log_id>', methods=['POST'])
def delete_log(log_id):
    logs = read_csv(LOGS_CSV)
    ids_to_delete = [log_id] + get_all_descendant_ids(logs, log_id)
    new_logs = [l for l in logs if l['id'] not in ids_to_delete]
    write_csv(LOGS_CSV, LOG_FIELDS, new_logs)
    return redirect(request.referrer or url_for('index'))

@app.route('/log/delete_by_site/<site_id>', methods=['POST'])
def delete_logs_by_site(site_id):
    logs = read_csv(LOGS_CSV)
    ids_to_delete = []
    for log in logs:
        if log['site_id'] == site_id:
            ids_to_delete.append(log['id'])
            ids_to_delete.extend(get_all_descendant_ids(logs, log['id']))
    new_logs = [l for l in logs if l['id'] not in ids_to_delete]
    write_csv(LOGS_CSV, LOG_FIELDS, new_logs)
    return redirect(url_for('index'))

@app.route('/log/delete_all', methods=['POST'])
def delete_all_logs():
    write_csv(LOGS_CSV, LOG_FIELDS, [])
    return redirect(url_for('index'))

@app.route('/sites')
def site_list():
    sites = read_csv(SITES_CSV)
    return render_template('site_list.html', sites=sites)

@app.route('/site/new', methods=['GET', 'POST'])
def add_site():
    if request.method == 'POST':
        sites = read_csv(SITES_CSV)
        sites.append({
            'id': str(uuid.uuid4()),
            'name': request.form.get('name'),
            'url': request.form.get('url')
        })
        write_csv(SITES_CSV, SITE_FIELDS, sites)
        return redirect(url_for('site_list'))
    return render_template('add_site.html')

@app.route('/site/edit/<site_id>', methods=['GET', 'POST'])
def edit_site(site_id):
    sites = read_csv(SITES_CSV)
    site = next((s for s in sites if s['id'] == site_id), None)
    if request.method == 'POST':
        if site:
            site['name'] = request.form.get('name')
            site['url'] = request.form.get('url')
            write_csv(SITES_CSV, SITE_FIELDS, sites)
        return redirect(url_for('site_list'))
    return render_template('edit_site.html', site=site)

@app.route('/site/delete/<site_id>', methods=['POST'])
def delete_site(site_id):
    sites = read_csv(SITES_CSV)
    new_sites = [s for s in sites if s['id'] != site_id]
    write_csv(SITES_CSV, SITE_FIELDS, new_sites)
    return redirect(url_for('site_list'))

@app.route('/memos')
def memo_list():
    memos = read_csv(MEMOS_CSV)
    sites = read_csv(SITES_CSV)
    site_map = {s['id']: s['name'] for s in sites}
    for m in memos: m['site_name'] = site_map.get(m['site_id'], '未指定')
    return render_template('memo_list.html', memos=memos, sites=sites)

@app.route('/memo/add', methods=['POST'])
def add_memo():
    memos = read_csv(MEMOS_CSV)
    memos.append({'id':str(uuid.uuid4()), 'site_id':request.form.get('site_id'), 'word':request.form.get('word'), 'description':request.form.get('description')})
    write_csv(MEMOS_CSV, MEMO_FIELDS, memos)
    return redirect(url_for('memo_list'))

@app.route('/memo/delete/<memo_id>', methods=['POST'])
def delete_memo(memo_id):
    memos = read_csv(MEMOS_CSV)
    write_csv(MEMOS_CSV, MEMO_FIELDS, [m for m in memos if m['id'] != memo_id])
    return redirect(request.referrer or url_for('memo_list'))

@app.route('/memo/convert/<memo_id>')
def convert_memo(memo_id):
    memos = read_csv(MEMOS_CSV)
    m = next((m for m in memos if m['id'] == memo_id), None)
    return redirect(url_for('add_log', initial_site_id=m['site_id'], initial_word=m['word'], initial_result=m['description']))

@app.route('/records')
def record_list():
    records = read_csv(RECORDS_CSV)
    return render_template('record_list.html', records=records)

@app.route('/record/new', methods=['GET', 'POST'])
def add_record():
    if request.method == 'POST':
        records = read_csv(RECORDS_CSV)
        records.append({'id':str(uuid.uuid4()), 'title':request.form.get('title'), 'content':request.form.get('content')})
        write_csv(RECORDS_CSV, RECORD_FIELDS, records)
        return redirect(url_for('record_list'))
    return render_template('edit_record.html', record=None)

@app.route('/record/edit/<record_id>', methods=['GET', 'POST'])
def edit_record(record_id):
    records = read_csv(RECORDS_CSV)
    r = next((r for r in records if r['id'] == record_id), None)
    if request.method == 'POST':
        r['title'], r['content'] = request.form.get('title'), request.form.get('content')
        write_csv(RECORDS_CSV, RECORD_FIELDS, records)
        return redirect(url_for('view_record', record_id=record_id))
    return render_template('edit_record.html', record=r)

@app.route('/record/delete/<record_id>', methods=['POST'])
def delete_record(record_id):
    records = read_csv(RECORDS_CSV)
    write_csv(RECORDS_CSV, RECORD_FIELDS, [r for r in records if r['id'] != record_id])
    return redirect(url_for('record_list'))

@app.route('/record/<record_id>')
def view_record(record_id):
    records = read_csv(RECORDS_CSV)
    r = next((r for r in records if r['id'] == record_id), None)
    if r: r['html_content'] = markdown.markdown(r['content'], extensions=['fenced_code', 'tables'])
    return render_template('view_record.html', record=r)

@app.route('/api/log/move', methods=['POST'])
def move_log():
    data = request.json
    dragged_id = str(data.get('log_id'))
    target_id = str(data.get('target_id')) if data.get('target_id') else None
    logs = read_csv(LOGS_CSV)
    dragged_log = next((l for l in logs if l['id'] == dragged_id), None)
    if not dragged_log: return {"status": "error"}, 404
    old_parent_id = dragged_log['parent_id']
    if not target_id:
        dragged_log['parent_id'] = None
    else:
        dragged_log['parent_id'] = target_id
    logs.append(logs.pop(logs.index(dragged_log)))
    write_csv(LOGS_CSV, LOG_FIELDS, logs)
    return {"status": "success"}

# --- 5. アプリ起動処理 (PyWebView + Flask) ---

def run_flask():
    # ポートは5001番を使用 (5000番の競合回避)
    app.run(host='127.0.0.1', port=5001, debug=False, threaded=True)

if __name__ == '__main__':
    # サーバーを別スレッドで起動
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

    # サーバー起動を待つ
    time.sleep(1.5)

    # 専用ウィンドウの作成と表示
    webview.create_window('検索ログ管理システム', 'http://127.0.0.1:5001/', width=1200, height=800)
    webview.start()