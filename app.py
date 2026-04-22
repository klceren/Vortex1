from flask import Flask, request, jsonify, send_file
import yt_dlp, os, threading, uuid, subprocess, socket, io, base64

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '127.0.0.1'

app = Flask(__name__)

jobs = {}

DOWNLOAD_DIR = "/home/claude/downloads"
UPLOAD_DIR = "/home/claude/uploads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

CONVERSIONS = {
    'mp3':  ['wav', 'ogg', 'flac', 'aac', 'm4a', 'opus'],
    'wav':  ['mp3', 'ogg', 'flac', 'aac', 'm4a'],
    'ogg':  ['mp3', 'wav', 'flac', 'aac'],
    'flac': ['mp3', 'wav', 'ogg', 'aac'],
    'aac':  ['mp3', 'wav', 'ogg', 'flac'],
    'm4a':  ['mp3', 'wav', 'ogg', 'flac'],
    'mp4':  ['avi', 'mkv', 'mov', 'webm', 'gif', 'mp3', 'wav'],
    'avi':  ['mp4', 'mkv', 'mov', 'webm', 'mp3'],
    'mkv':  ['mp4', 'avi', 'mov', 'webm', 'mp3'],
    'mov':  ['mp4', 'avi', 'mkv', 'webm', 'mp3'],
    'webm': ['mp4', 'avi', 'mkv', 'mp3'],
    'jpg':  ['png', 'webp', 'bmp', 'gif', 'tiff'],
    'jpeg': ['png', 'webp', 'bmp', 'gif', 'tiff'],
    'png':  ['jpg', 'webp', 'bmp', 'gif', 'tiff'],
    'webp': ['jpg', 'png', 'bmp'],
    'bmp':  ['jpg', 'png', 'webp'],
    'gif':  ['mp4', 'webm', 'png'],
    'tiff': ['jpg', 'png', 'webp'],
}

def make_progress_hook(job_id):
    def hook(d):
        if d['status'] == 'downloading':
            jobs[job_id]['progress'] = d.get('_percent_str', '?').strip()
            jobs[job_id]['speed'] = d.get('_speed_str', '').strip()
            jobs[job_id]['eta'] = d.get('_eta_str', '').strip()
            jobs[job_id]['status'] = 'downloading'
        elif d['status'] == 'finished':
            jobs[job_id]['status'] = 'processing'
    return hook

def run_download(job_id, url, fmt, quality):
    try:
        if fmt == 'audio':
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'{DOWNLOAD_DIR}/{job_id}/%(title)s.%(ext)s',
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
                'progress_hooks': [make_progress_hook(job_id)],
                'quiet': True,
            }
        else:
            q_map = {'best': 'bestvideo+bestaudio/best', '1080': 'bestvideo[height<=1080]+bestaudio/best', '720': 'bestvideo[height<=720]+bestaudio/best', '480': 'bestvideo[height<=480]+bestaudio/best'}
            ydl_opts = {
                'format': q_map.get(quality, 'bestvideo+bestaudio/best'),
                'outtmpl': f'{DOWNLOAD_DIR}/{job_id}/%(title)s.%(ext)s',
                'merge_output_format': 'mp4',
                'progress_hooks': [make_progress_hook(job_id)],
                'quiet': True,
            }
        os.makedirs(f'{DOWNLOAD_DIR}/{job_id}', exist_ok=True)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            jobs[job_id]['title'] = info.get('title', 'video')
        files = os.listdir(f'{DOWNLOAD_DIR}/{job_id}')
        if files:
            jobs[job_id]['file'] = f'{DOWNLOAD_DIR}/{job_id}/{files[0]}'
            jobs[job_id]['filename'] = files[0]
            jobs[job_id]['status'] = 'done'
        else:
            jobs[job_id]['status'] = 'error'
            jobs[job_id]['error'] = 'Dosya bulunamadı'
    except Exception as e:
        jobs[job_id]['status'] = 'error'
        jobs[job_id]['error'] = str(e)

def run_convert(job_id, input_path, output_ext, original_name):
    try:
        jobs[job_id]['status'] = 'processing'
        base = os.path.splitext(original_name)[0]
        out_filename = f'{base}.{output_ext}'
        out_path = f'{DOWNLOAD_DIR}/{job_id}/{out_filename}'
        os.makedirs(f'{DOWNLOAD_DIR}/{job_id}', exist_ok=True)
        cmd = ['ffmpeg', '-y', '-i', input_path]
        if output_ext == 'gif':
            cmd += ['-vf', 'fps=10,scale=480:-1:flags=lanczos', '-loop', '0']
        elif output_ext == 'mp3':
            cmd += ['-q:a', '2']
        cmd.append(out_path)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and os.path.exists(out_path):
            jobs[job_id]['file'] = out_path
            jobs[job_id]['filename'] = out_filename
            jobs[job_id]['status'] = 'done'
        else:
            jobs[job_id]['status'] = 'error'
            jobs[job_id]['error'] = result.stderr[-300:] if result.stderr else 'Dönüştürme başarısız'
    except Exception as e:
        jobs[job_id]['status'] = 'error'
        jobs[job_id]['error'] = str(e)
    finally:
        try:
            os.remove(input_path)
        except:
            pass

def run_cut(job_id, input_path, start_sec, end_sec, original_name):
    try:
        jobs[job_id]['status'] = 'processing'
        base, ext = os.path.splitext(original_name)
        out_filename = f'{base}_cut{ext}'
        out_path = f'{DOWNLOAD_DIR}/{job_id}/{out_filename}'
        os.makedirs(f'{DOWNLOAD_DIR}/{job_id}', exist_ok=True)
        duration = end_sec - start_sec
        ext_lower = ext.lower().lstrip('.')
        # For audio-only formats use copy codec, for video use re-encode for accuracy
        if ext_lower in ['mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a', 'opus']:
            cmd = ['ffmpeg', '-y', '-i', input_path, '-ss', str(start_sec), '-t', str(duration), '-acodec', 'copy', out_path]
        else:
            cmd = ['ffmpeg', '-y', '-ss', str(start_sec), '-i', input_path, '-t', str(duration), '-c', 'copy', out_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and os.path.exists(out_path):
            jobs[job_id]['file'] = out_path
            jobs[job_id]['filename'] = out_filename
            jobs[job_id]['status'] = 'done'
        else:
            jobs[job_id]['status'] = 'error'
            jobs[job_id]['error'] = result.stderr[-300:] if result.stderr else 'Kesme başarısız'
    except Exception as e:
        jobs[job_id]['status'] = 'error'
        jobs[job_id]['error'] = str(e)
    finally:
        try:
            os.remove(input_path)
        except:
            pass

def get_media_duration(path):
    result = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', path],
        capture_output=True, text=True
    )
    import json
    try:
        data = json.loads(result.stdout)
        return float(data['format']['duration'])
    except:
        return 0

@app.route('/info', methods=['POST'])
def get_info():
    url = request.json.get('url', '').strip()
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            return jsonify({'title': info.get('title', ''), 'thumbnail': info.get('thumbnail', ''), 'duration': info.get('duration', 0), 'uploader': info.get('uploader', '')})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/download', methods=['POST'])
def start_download():
    data = request.json
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {'status': 'starting', 'progress': '0%', 'speed': '', 'eta': '', 'title': '', 'file': None, 'filename': None}
    t = threading.Thread(target=run_download, args=(job_id, data.get('url','').strip(), data.get('format','video'), data.get('quality','best')))
    t.daemon = True
    t.start()
    return jsonify({'job_id': job_id})

@app.route('/convert/formats', methods=['POST'])
def get_formats():
    ext = request.json.get('ext', '').lower().lstrip('.')
    return jsonify({'formats': CONVERSIONS.get(ext, [])})

@app.route('/convert', methods=['POST'])
def start_convert():
    if 'file' not in request.files:
        return jsonify({'error': 'Dosya seçilmedi'}), 400
    file = request.files['file']
    output_ext = request.form.get('output_ext', '').lower().strip('.')
    original_name = file.filename
    input_ext = os.path.splitext(original_name)[1].lower().lstrip('.')
    if input_ext not in CONVERSIONS or output_ext not in CONVERSIONS.get(input_ext, []):
        return jsonify({'error': f'{input_ext} → {output_ext} dönüşümü desteklenmiyor'}), 400
    job_id = str(uuid.uuid4())[:8]
    save_path = f'{UPLOAD_DIR}/{job_id}_{original_name}'
    file.save(save_path)
    jobs[job_id] = {'status': 'starting', 'progress': '100%', 'speed': '', 'eta': '', 'title': original_name, 'file': None, 'filename': None}
    t = threading.Thread(target=run_convert, args=(job_id, save_path, output_ext, original_name))
    t.daemon = True
    t.start()
    return jsonify({'job_id': job_id})

@app.route('/cut/probe', methods=['POST'])
def cut_probe():
    if 'file' not in request.files:
        return jsonify({'error': 'Dosya seçilmedi'}), 400
    file = request.files['file']
    original_name = file.filename
    job_id = str(uuid.uuid4())[:8]
    save_path = f'{UPLOAD_DIR}/probe_{job_id}_{original_name}'
    file.save(save_path)
    duration = get_media_duration(save_path)
    # Keep file for later cut operation, return a probe_id
    return jsonify({'probe_id': job_id, 'filename': original_name, 'duration': duration})

@app.route('/cut', methods=['POST'])
def start_cut():
    if 'file' not in request.files:
        return jsonify({'error': 'Dosya seçilmedi'}), 400
    file = request.files['file']
    start_sec = float(request.form.get('start', 0))
    end_sec = float(request.form.get('end', 0))
    original_name = file.filename
    if end_sec <= start_sec:
        return jsonify({'error': 'Bitiş zamanı başlangıçtan büyük olmalı'}), 400
    job_id = str(uuid.uuid4())[:8]
    save_path = f'{UPLOAD_DIR}/{job_id}_{original_name}'
    file.save(save_path)
    jobs[job_id] = {'status': 'starting', 'progress': '100%', 'speed': '', 'eta': '', 'title': original_name, 'file': None, 'filename': None}
    t = threading.Thread(target=run_cut, args=(job_id, save_path, start_sec, end_sec, original_name))
    t.daemon = True
    t.start()
    return jsonify({'job_id': job_id})

@app.route('/status/<job_id>')
def status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify(job)

TRANSFER_DIR = os.path.join(os.path.dirname(__file__), 'transfers')
os.makedirs(TRANSFER_DIR, exist_ok=True)

# ===== GÖREV LİSTESİ =====
import json as _json
TODO_FILE = os.path.join(os.path.dirname(__file__), 'todos.json')

def load_todos():
    if not os.path.exists(TODO_FILE):
        return []
    try:
        with open(TODO_FILE, 'r', encoding='utf-8') as f:
            return _json.load(f)
    except:
        return []

def save_todos(todos):
    with open(TODO_FILE, 'w', encoding='utf-8') as f:
        _json.dump(todos, f, ensure_ascii=False, indent=2)

@app.route('/todos', methods=['GET'])
def get_todos():
    return jsonify(load_todos())

@app.route('/todos/add', methods=['POST'])
def add_todo():
    text = request.json.get('text', '').strip()
    if not text:
        return jsonify({'error': 'Görev boş olamaz'}), 400
    todos = load_todos()
    todo = {'id': str(uuid.uuid4())[:8], 'text': text, 'done': False}
    todos.append(todo)
    save_todos(todos)
    return jsonify(todo)

@app.route('/todos/toggle/<todo_id>', methods=['POST'])
def toggle_todo(todo_id):
    todos = load_todos()
    for t in todos:
        if t['id'] == todo_id:
            t['done'] = not t['done']
            save_todos(todos)
            return jsonify(t)
    return jsonify({'error': 'Görev bulunamadı'}), 404

@app.route('/todos/delete/<todo_id>', methods=['POST'])
def delete_todo(todo_id):
    todos = load_todos()
    todos = [t for t in todos if t['id'] != todo_id]
    save_todos(todos)
    return jsonify({'ok': True})

@app.route('/todos/clear', methods=['POST'])
def clear_todos():
    save_todos([])
    return jsonify({'ok': True})

@app.route('/transfer/qr')
def transfer_qr():
    # _make_qr ile https:// URL üretiyoruz — sunucu HTTPS modunda çalışıyor
    b64, url = _make_qr('/transfer/mobile')
    if not b64:
        return jsonify({'error': 'qrcode kütüphanesi eksik: pip install qrcode[pil]'}), 500
    ip = get_local_ip()
    return jsonify({'qr': b64, 'url': url, 'ip': ip})

@app.route('/transfer/mobile')
def transfer_mobile():
    html = '''<!DOCTYPE html><html lang="tr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VORTEX Transfer</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0a;color:#f0f0f0;font-family:system-ui,sans-serif;min-height:100vh;padding:20px 16px 40px;display:flex;flex-direction:column;gap:20px}
.logo{font-family:monospace;font-size:1.4rem;letter-spacing:.2em;color:#e8ff00;text-align:center;padding:8px 0}
.sub{font-family:monospace;font-size:.55rem;color:#444;letter-spacing:.2em;text-transform:uppercase;text-align:center;margin-top:2px}
.section{background:#111;border:1px solid #222;padding:16px}
.section-title{font-family:monospace;font-size:.6rem;letter-spacing:.2em;color:#555;text-transform:uppercase;margin-bottom:14px;display:flex;align-items:center;gap:8px}
.section-title span{color:#e8ff00}
/* UPLOAD */
.drop{border:2px dashed #2a2a2a;padding:28px 16px;text-align:center;cursor:pointer;position:relative;transition:border-color .2s;border-radius:2px}
.drop.over{border-color:#e8ff00;background:rgba(232,255,0,.03)}
.drop input{position:absolute;inset:0;opacity:0;width:100%;height:100%;cursor:pointer}
.drop-icon{font-size:2rem;margin-bottom:6px}
.drop-hint{font-family:monospace;font-size:.65rem;color:#555;letter-spacing:.08em}
.file-list{display:flex;flex-direction:column;gap:6px;margin-top:12px}
.file-item{background:#161616;border:1px solid #1e1e1e;padding:10px 12px;display:flex;flex-direction:column;gap:4px}
.file-name{font-family:monospace;font-size:.65rem;color:#e8ff00;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar-track{height:2px;background:#222}
.bar-fill{height:100%;background:#e8ff00;width:0%;transition:width .3s}
.file-status{font-family:monospace;font-size:.55rem;color:#444}
.file-status.done{color:#e8ff00}.file-status.err{color:#ff4d00}
/* DOWNLOAD */
.dl-item{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid #1a1a1a}
.dl-item:last-child{border-bottom:none}
.dl-info{flex:1;overflow:hidden}
.dl-name{font-family:monospace;font-size:.65rem;color:#f0f0f0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dl-size{font-family:monospace;font-size:.55rem;color:#444;margin-top:2px}
.dl-btn{font-family:monospace;font-size:.6rem;letter-spacing:.08em;padding:8px 14px;border:1px solid #2a2a2a;background:#0a0a0a;color:#888;text-decoration:none;display:flex;align-items:center;gap:5px;flex-shrink:0;transition:all .15s}
.dl-btn:active{border-color:#e8ff00;color:#e8ff00}
.empty{font-family:monospace;font-size:.65rem;color:#333;text-align:center;padding:20px 0;letter-spacing:.1em}
.refresh{font-family:monospace;font-size:.55rem;letter-spacing:.1em;padding:5px 10px;border:1px solid #222;background:none;color:#444;cursor:pointer;text-transform:uppercase;float:right;margin-top:-2px}
</style></head>
<body>
<div><div class="logo">VORTEX</div><div class="sub">Dosya Transfer</div></div>

<!-- TELEFONA GÖNDER (bilgisayardan indir) -->
<div class="section">
  <div class="section-title"><span>⬇</span> BİLGİSAYARDAN İNDİR <button class="refresh" onclick="loadFiles()">↻</button></div>
  <div id="dl-list"><div class="empty">Yükleniyor...</div></div>
</div>

<!-- BİLGİSAYARA GÖNDER -->
<div class="section">
  <div class="section-title"><span>⬆</span> BİLGİSAYARA GÖNDER</div>
  <div class="drop" id="drop">
    <input type="file" multiple onchange="handleFiles(this.files)">
    <div class="drop-icon">📤</div>
    <div class="drop-hint">Dosya seç veya sürükle</div>
  </div>
  <div class="file-list" id="file-list"></div>
</div>

<script>
// ---- İNDİRME LİSTESİ ----
async function loadFiles(){
  const list=document.getElementById('dl-list');
  list.innerHTML='<div class="empty">Yükleniyor...</div>';
  try{
    const res=await fetch('/transfer/files');
    const data=await res.json();
    if(!data.files.length){list.innerHTML='<div class="empty">Henüz dosya yok</div>';return}
    list.innerHTML=data.files.map(f=>{
      const name=f.name.includes('_')?f.name.split('_').slice(1).join('_'):f.name;
      const size=f.size>1048576?(f.size/1048576).toFixed(1)+' MB':(f.size/1024).toFixed(0)+' KB';
      return `<div class="dl-item">
        <div class="dl-info"><div class="dl-name">${name}</div><div class="dl-size">${size}</div></div>
        <a class="dl-btn" href="/transfer/files/${f.name}" download="${name}">⬇ İndir</a>
      </div>`;
    }).join('');
  }catch(e){list.innerHTML='<div class="empty">Bağlantı hatası</div>'}
}
loadFiles();

// ---- YÜKLEME ----
const drop=document.getElementById('drop');
drop.addEventListener('dragover',e=>{e.preventDefault();drop.classList.add('over')});
drop.addEventListener('dragleave',()=>drop.classList.remove('over'));
drop.addEventListener('drop',e=>{e.preventDefault();drop.classList.remove('over');handleFiles(e.dataTransfer.files)});
function handleFiles(files){[...files].forEach(uploadFile)}
function uploadFile(file){
  const id='f'+Date.now()+Math.random().toString(36).slice(2);
  const list=document.getElementById('file-list');
  const item=document.createElement('div');item.className='file-item';item.id=id;
  item.innerHTML=`<div class="file-name">${file.name}</div><div class="bar-track"><div class="bar-fill" id="bar-${id}"></div></div><div class="file-status" id="st-${id}">Yükleniyor...</div>`;
  list.prepend(item);
  const fd=new FormData();fd.append('file',file);
  const xhr=new XMLHttpRequest();
  xhr.open('POST','/transfer/upload');
  xhr.upload.onprogress=e=>{if(e.lengthComputable){const p=(e.loaded/e.total*100).toFixed(0);document.getElementById('bar-'+id).style.width=p+'%';document.getElementById('st-'+id).textContent=p+'%'}};
  xhr.onload=()=>{
    const st=document.getElementById('st-'+id);
    if(xhr.status===200){document.getElementById('bar-'+id).style.width='100%';st.textContent='✓ Tamamlandı';st.className='file-status done';loadFiles()}
    else{st.textContent='⚠ Hata';st.className='file-status err'}
  };
  xhr.onerror=()=>{document.getElementById('st-'+id).textContent='⚠ Bağlantı hatası';document.getElementById('st-'+id).className='file-status err'};
  xhr.send(fd);
}
</script></body></html>'''
    return html

@app.route('/transfer/upload', methods=['POST'])
def transfer_upload():
    if 'file' not in request.files:
        return jsonify({'error': 'Dosya bulunamadı'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'Dosya adı boş'}), 400
    safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    save_path = os.path.join(TRANSFER_DIR, safe_name)
    file.save(save_path)
    return jsonify({'ok': True, 'filename': file.filename, 'saved_as': safe_name})

@app.route('/transfer/files')
def transfer_files():
    files = []
    for f in sorted(os.listdir(TRANSFER_DIR), key=lambda x: os.path.getmtime(os.path.join(TRANSFER_DIR, x)), reverse=True):
        fp = os.path.join(TRANSFER_DIR, f)
        files.append({'name': f, 'size': os.path.getsize(fp)})
    return jsonify({'files': files})

@app.route('/transfer/files/<filename>')
def transfer_download(filename):
    fp = os.path.join(TRANSFER_DIR, filename)
    if not os.path.exists(fp):
        return 'Not found', 404
    return send_file(fp, as_attachment=True, download_name=filename.split('_', 1)[-1] if '_' in filename else filename)

@app.route('/file/<job_id>')
def get_file(job_id):
    job = jobs.get(job_id)
    if not job or not job.get('file'):
        return 'Not found', 404
    return send_file(job['file'], as_attachment=True, download_name=job['filename'])

@app.route('/')
def index():
    return send_file(os.path.join(os.path.dirname(__file__), 'index.html'))

# ─────────────────────────────────────────────
# CLIPBOARD
# ─────────────────────────────────────────────
_clipboard_text = ''
_clipboard_lock = threading.Lock()

@app.route('/clipboard/send', methods=['POST'])
def clipboard_send():
    global _clipboard_text
    text = request.json.get('text', '')
    with _clipboard_lock:
        _clipboard_text = text
    try:
        import pyperclip; pyperclip.copy(text)
    except Exception:
        pass
    return jsonify({'ok': True})

@app.route('/clipboard/receive')
def clipboard_receive():
    with _clipboard_lock:
        return jsonify({'text': _clipboard_text})

@app.route('/clipboard/qr')
def clipboard_qr():
    b64, url = _make_qr('/')
    if not b64:
        return jsonify({'error': 'pip install qrcode[pil]'}), 500
    return jsonify({'qr': b64, 'url': url})

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def _make_qr(path):
    try:
        import qrcode as _qrc
    except ImportError:
        return None, None
    ip  = get_local_ip()
    url = f'https://{ip}:7861{path}'
    qr  = _qrc.QRCode(box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color='#e8ff00', back_color='#111111')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode(), url

# ─────────────────────────────────────────────
# CAMERA  (MJPEG + OpenCV recorder)
# ─────────────────────────────────────────────
import time as _time

RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), 'recordings')
os.makedirs(RECORDINGS_DIR, exist_ok=True)

_cam_frame = None
_cam_lock  = threading.Lock()
_rec_state = {'recording': False, 'writer': None, 'filename': None,
              'frame_count': 0, 'start_time': None}
_rec_lock  = threading.Lock()

@app.route('/camera/qr')
def camera_qr():
    b64, url = _make_qr('/camera/mobile')
    if not b64:
        return jsonify({'error': 'pip install qrcode[pil]'}), 500
    return jsonify({'qr': b64, 'url': url})

@app.route('/camera/mobile')
def camera_mobile():
    ip = get_local_ip()
    html = f'''<!DOCTYPE html><html lang="tr"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>VORTEX Kamera</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0a0a;color:#f0f0f0;font-family:system-ui,sans-serif;
     display:flex;flex-direction:column;align-items:center;
     min-height:100vh;padding:16px;gap:14px;padding-bottom:40px}}
.logo{{font-family:monospace;font-size:1.3rem;letter-spacing:.2em;color:#e8ff00;margin-top:8px}}
.sub{{font-family:monospace;font-size:.55rem;color:#444;letter-spacing:.2em;text-transform:uppercase}}
video{{width:100%;max-width:480px;border:1px solid #222;background:#000;border-radius:2px;
      transform:scaleX(-1)}}
.status{{font-family:monospace;font-size:.65rem;color:#555;letter-spacing:.1em;text-align:center;padding:4px 0}}
.status.live{{color:#e8ff00}}
.status.err{{color:#ff4d00}}
.btn{{width:100%;max-width:480px;padding:16px;background:none;
     border:2px solid #e8ff00;color:#e8ff00;font-family:monospace;
     font-size:.9rem;letter-spacing:.15em;text-transform:uppercase;cursor:pointer;transition:all .15s}}
.btn:active,.btn:focus{{background:#e8ff00;color:#000;outline:none}}
.btn.stop{{border-color:#ff4d00;color:#ff4d00}}
.btn.stop:active{{background:#ff4d00;color:#fff}}
.btn.secondary{{border-color:#333;color:#555;font-size:.7rem;padding:10px}}
</style></head><body>
<div class="logo">VORTEX</div>
<div class="sub">Uzaktan Kamera</div>
<video id="vid" autoplay playsinline muted></video>
<div class="status" id="st">Kamera başlatılıyor...</div>
<button class="btn" id="mainBtn" onclick="handleMainBtn()">📡 YAYINI BAŞLAT</button>
<button class="btn secondary" onclick="flipCamera()">🔄 Ön / Arka Kamera</button>
<script>
const HOST=location.origin;
let stream=null,intervalId=null,facingMode='environment',streaming=false;

async function startCam(){{
  if(stream){{ stream.getTracks().forEach(t=>t.stop()); stream=null; }}
  const st=document.getElementById('st');
  try{{
    stream=await navigator.mediaDevices.getUserMedia({{
      video:{{facingMode,width:{{ideal:1280}},height:{{ideal:720}}}},audio:false
    }});
    document.getElementById('vid').srcObject=stream;
    st.textContent='✓ Kamera hazır — Yayını başlatmak için butona bas';
    st.className='status';
  }}catch(e){{
    st.textContent='⚠ Kamera hatası: '+e.message;
    st.className='status err';
  }}
}}

function handleMainBtn(){{
  if(!streaming) startStream(); else stopStream();
}}

async function startStream(){{
  if(!stream) await startCam();
  if(!stream) return;
  streaming=true;
  const btn=document.getElementById('mainBtn');
  btn.textContent='⏹ YAYINI DURDUR';
  btn.className='btn stop';
  document.getElementById('st').textContent='● CANLI YAYIN';
  document.getElementById('st').className='status live';
  const canvas=document.createElement('canvas');
  const vid=document.getElementById('vid');
  intervalId=setInterval(async()=>{{
    if(!streaming||!stream) return;
    canvas.width=vid.videoWidth||640;
    canvas.height=vid.videoHeight||480;
    const ctx=canvas.getContext('2d');
    // Mirror front camera back to normal for recording
    ctx.save();
    if(facingMode==='user'){{ctx.scale(-1,1);ctx.drawImage(vid,-canvas.width,0,canvas.width,canvas.height);}}
    else{{ ctx.drawImage(vid,0,0,canvas.width,canvas.height); }}
    ctx.restore();
    canvas.toBlob(async blob=>{{
      if(!blob) return;
      try{{ await fetch(HOST+'/camera/frame',{{method:'POST',body:blob,headers:{{'Content-Type':'image/jpeg'}}}}); }}
      catch(e){{}}
    }},'image/jpeg',0.75);
  }},100);
}}

function stopStream(){{
  streaming=false;
  if(intervalId){{ clearInterval(intervalId); intervalId=null; }}
  const btn=document.getElementById('mainBtn');
  btn.textContent='📡 YAYINI BAŞLAT';
  btn.className='btn';
  document.getElementById('st').textContent='Yayın durduruldu';
  document.getElementById('st').className='status';
}}

async function flipCamera(){{
  facingMode=facingMode==='environment'?'user':'environment';
  const was=streaming;
  if(streaming) stopStream();
  await startCam();
  if(was) startStream();
}}

startCam();
</script></body></html>'''
    return html

@app.route('/camera/frame', methods=['POST'])
def camera_frame():
    global _cam_frame
    data = request.get_data()
    if not data:
        return '', 204
    with _cam_lock:
        _cam_frame = data
    with _rec_lock:
        if _rec_state['recording'] and _rec_state['writer']:
            try:
                import cv2, numpy as np
                arr   = np.frombuffer(data, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    _rec_state['writer'].write(frame)
                    _rec_state['frame_count'] += 1
            except Exception as e:
                print(f'[CAM] write err: {e}')
    return '', 204

@app.route('/camera/stream')
def camera_stream():
    from flask import Response
    def gen():
        blank = None
        while True:
            with _cam_lock:
                frame = _cam_frame
            if frame:
                yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n'
            else:
                if blank is None:
                    try:
                        import cv2, numpy as np
                        img = np.zeros((240,320,3), dtype=np.uint8)
                        cv2.putText(img,'Telefon bekleniyor...',(30,125),
                                    cv2.FONT_HERSHEY_SIMPLEX,0.55,(60,60,60),1)
                        _,buf = cv2.imencode('.jpg',img)
                        blank = buf.tobytes()
                    except Exception:
                        blank = b''
                if blank:
                    yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + blank + b'\r\n'
            _time.sleep(0.05)
    return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/camera/record/start', methods=['POST'])
def camera_record_start():
    with _rec_lock:
        if _rec_state['recording']:
            return jsonify({'ok': False, 'error': 'Zaten kaydediliyor'})
        try:
            import cv2, numpy as np
            with _cam_lock:
                fd = _cam_frame
            if not fd:
                return jsonify({'ok': False, 'error': 'Önce telefon yayını başlat'}), 400
            arr   = np.frombuffer(fd, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                return jsonify({'ok': False, 'error': 'Frame çözümlenemedi'}), 400
            h, w  = frame.shape[:2]
            fname = f'rec_{int(_time.time())}.mp4'
            fpath = os.path.join(RECORDINGS_DIR, fname)
            writer = cv2.VideoWriter(fpath, cv2.VideoWriter_fourcc(*'mp4v'), 10.0, (w, h))
            _rec_state.update({'recording': True, 'writer': writer, 'filename': fname,
                               'frame_count': 0, 'start_time': _time.time()})
            return jsonify({'ok': True, 'filename': fname})
        except ImportError:
            return jsonify({'ok': False, 'error': 'pip install opencv-python'}), 500
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/camera/record/stop', methods=['POST'])
def camera_record_stop():
    with _rec_lock:
        if not _rec_state['recording']:
            return jsonify({'ok': False, 'error': 'Kayıt yok'})
        writer   = _rec_state['writer']
        fname    = _rec_state['filename']
        frames   = _rec_state['frame_count']
        duration = round(_time.time() - (_rec_state['start_time'] or _time.time()), 1)
        _rec_state.update({'recording': False, 'writer': None,
                           'filename': None, 'frame_count': 0, 'start_time': None})
    if writer:
        try: writer.release()
        except Exception: pass
    return jsonify({'ok': True, 'filename': fname, 'frames': frames, 'duration': duration})

@app.route('/camera/record/status')
def camera_record_status():
    with _rec_lock:
        elapsed = round(_time.time() - _rec_state['start_time'], 1) if _rec_state['start_time'] else 0
        return jsonify({'recording': _rec_state['recording'],
                        'filename':  _rec_state['filename'],
                        'frame_count': _rec_state['frame_count'],
                        'elapsed': elapsed})

@app.route('/camera/recordings')
def camera_recordings():
    files = []
    for f in sorted(os.listdir(RECORDINGS_DIR),
                    key=lambda x: os.path.getmtime(os.path.join(RECORDINGS_DIR, x)), reverse=True):
        if f.endswith('.mp4'):
            fp = os.path.join(RECORDINGS_DIR, f)
            files.append({'name': f, 'size': os.path.getsize(fp)})
    return jsonify({'files': files})

@app.route('/camera/recordings/<filename>')
def camera_download(filename):
    fp = os.path.join(RECORDINGS_DIR, filename)
    if not os.path.exists(fp): return 'Not found', 404
    return send_file(fp, as_attachment=True, download_name=filename)

# ─────────────────────────────────────────────
# SCRCPY MIRROR  (USB/Wi-Fi telefon yansıtma)
# ─────────────────────────────────────────────
import shutil

_scrcpy_proc  = None
_scrcpy_lock  = threading.Lock()

def _scrcpy_path():
    """scrcpy binary'sini bul."""
    p = shutil.which('scrcpy')
    if p: return p
    # Windows yaygın konumlar
    for candidate in [
        r'C:\scrcpy\scrcpy.exe',
        r'C:\Program Files\scrcpy\scrcpy.exe',
        os.path.join(os.path.dirname(__file__), 'scrcpy', 'scrcpy.exe'),
        os.path.join(os.path.dirname(__file__), 'scrcpy.exe'),
    ]:
        if os.path.exists(candidate):
            return candidate
    return None

def _adb_path():
    p = shutil.which('adb')
    if p: return p
    for candidate in [
        r'C:\scrcpy\adb.exe',
        os.path.join(os.path.dirname(__file__), 'scrcpy', 'adb.exe'),
        os.path.join(os.path.dirname(__file__), 'adb.exe'),
    ]:
        if os.path.exists(candidate):
            return candidate
    return None

@app.route('/mirror/status')
def mirror_status():
    scrcpy = _scrcpy_path()
    adb    = _adb_path()
    with _scrcpy_lock:
        running = _scrcpy_proc is not None and _scrcpy_proc.poll() is None
    # Bağlı cihazlar
    devices = []
    if adb:
        try:
            r = subprocess.run([adb, 'devices'], capture_output=True, text=True, timeout=5)
            for line in r.stdout.splitlines()[1:]:
                line = line.strip()
                if line and '\t' in line:
                    serial, state = line.split('\t', 1)
                    if state.strip() == 'device':
                        devices.append(serial.strip())
        except Exception:
            pass
    return jsonify({
        'scrcpy_found': bool(scrcpy),
        'adb_found':    bool(adb),
        'running':      running,
        'devices':      devices,
        'scrcpy_path':  scrcpy or '',
        'adb_path':     adb or '',
    })

@app.route('/mirror/start', methods=['POST'])
def mirror_start():
    global _scrcpy_proc
    data    = request.json or {}
    serial  = data.get('serial', '')      # belirli cihaz
    bitrate = data.get('bitrate', '8M')
    maxfps  = data.get('maxfps', '60')
    maxsize = data.get('maxsize', '1080')
    extra   = data.get('extra', '')       # ek argümanlar

    scrcpy = _scrcpy_path()
    if not scrcpy:
        return jsonify({'ok': False, 'error': 'scrcpy bulunamadı. Kurulum talimatlarına bakın.'}), 404

    with _scrcpy_lock:
        # Varsa eski süreci öldür
        if _scrcpy_proc and _scrcpy_proc.poll() is None:
            _scrcpy_proc.terminate()
            try: _scrcpy_proc.wait(timeout=3)
            except: pass

        cmd = [scrcpy, '--video-bit-rate', bitrate, '--max-fps', maxfps, '--max-size', maxsize]
        if serial:
            cmd += ['-s', serial]
        if extra:
            cmd += extra.split()
        try:
            _scrcpy_proc = subprocess.Popen(cmd,
                stdout=open('C:\\Users\\w11\\Desktop\\video-indirici\\scrcpy_log.txt','w'), stderr=subprocess.STDOUT,
                cwd=os.path.dirname(os.path.abspath(__file__)))
            return jsonify({'ok': True, 'pid': _scrcpy_proc.pid, 'cmd': ' '.join(cmd)})
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/mirror/stop', methods=['POST'])
def mirror_stop():
    global _scrcpy_proc
    with _scrcpy_lock:
        if _scrcpy_proc and _scrcpy_proc.poll() is None:
            _scrcpy_proc.terminate()
            try: _scrcpy_proc.wait(timeout=3)
            except: _scrcpy_proc.kill()
        _scrcpy_proc = None
    return jsonify({'ok': True})

@app.route('/mirror/adb/devices')
def mirror_adb_devices():
    adb = _adb_path()
    if not adb:
        return jsonify({'ok': False, 'error': 'adb bulunamadı', 'devices': []})
    try:
        r = subprocess.run([adb, 'devices', '-l'], capture_output=True, text=True, timeout=6)
        devices = []
        for line in r.stdout.splitlines()[1:]:
            line = line.strip()
            if not line or 'offline' in line: continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == 'device':
                info = {'serial': parts[0]}
                for p in parts[2:]:
                    if ':' in p:
                        k, v = p.split(':', 1)
                        info[k] = v
                devices.append(info)
        return jsonify({'ok': True, 'devices': devices})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e), 'devices': []})

@app.route('/mirror/adb/tcpip', methods=['POST'])
def mirror_adb_tcpip():
    """Wi-Fi moduna geçiş için ADB TCP/IP etkinleştir."""
    adb = _adb_path()
    if not adb:
        return jsonify({'ok': False, 'error': 'adb bulunamadı'})
    serial = (request.json or {}).get('serial', '')
    cmd = [adb]
    if serial: cmd += ['-s', serial]
    cmd += ['tcpip', '5555']
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        return jsonify({'ok': r.returncode == 0, 'output': r.stdout + r.stderr})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/mirror/adb/connect', methods=['POST'])
def mirror_adb_connect():
    """Wi-Fi IP ile ADB bağlan."""
    adb = _adb_path()
    if not adb:
        return jsonify({'ok': False, 'error': 'adb bulunamadı'})
    ip   = (request.json or {}).get('ip', '')
    port = (request.json or {}).get('port', '5555')
    if not ip:
        return jsonify({'ok': False, 'error': 'IP adresi gerekli'})
    try:
        r = subprocess.run([adb, 'connect', f'{ip}:{port}'],
                           capture_output=True, text=True, timeout=10)
        ok = 'connected' in r.stdout.lower() or 'already' in r.stdout.lower()
        return jsonify({'ok': ok, 'output': r.stdout + r.stderr})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

# ─────────────────────────────────────────────
# SSL — self-signed sertifika otomatik üretilir
# ─────────────────────────────────────────────
def _ensure_ssl():
    cert = os.path.join(os.path.dirname(__file__), 'cert.pem')
    key  = os.path.join(os.path.dirname(__file__), 'key.pem')
    if not (os.path.exists(cert) and os.path.exists(key)):
        print('[SSL] Sertifika üretiliyor...')
        try:
            from cryptography import x509
            from cryptography.x509.oid import NameOID
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            import datetime, ipaddress
            privkey = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            ip_str  = get_local_ip()
            subject = issuer = x509.Name([
                x509.NameAttribute(NameOID.COMMON_NAME, ip_str)
            ])
            san = x509.SubjectAlternativeName([
                x509.DNSName('localhost'),
                x509.IPAddress(ipaddress.IPv4Address(ip_str)),
                x509.IPAddress(ipaddress.IPv4Address('127.0.0.1')),
            ])
            cert_obj = (x509.CertificateBuilder()
                .subject_name(subject).issuer_name(issuer)
                .public_key(privkey.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(datetime.datetime.utcnow())
                .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
                .add_extension(san, critical=False)
                .sign(privkey, hashes.SHA256()))
            with open(cert, 'wb') as f:
                f.write(cert_obj.public_bytes(serialization.Encoding.PEM))
            with open(key, 'wb') as f:
                f.write(privkey.private_bytes(serialization.Encoding.PEM,
                    serialization.PrivateFormat.TraditionalOpenSSL,
                    serialization.NoEncryption()))
            print(f'[SSL] Sertifika oluşturuldu → {cert}')
        except ImportError:
            print('[SSL] cryptography paketi yok — pip install cryptography')
            return None, None
        except Exception as e:
            print(f'[SSL] Hata: {e}')
            return None, None
    return cert, key

if __name__ == '__main__':
    cert, key = _ensure_ssl()
    ip = get_local_ip()
    if cert and key:
        print(f'\n  🔒 HTTPS aktif  →  https://{ip}:7861')
        print(f'  📱 Telefonda "Güvensiz bağlantı" uyarısı çıkarsa "İlerle/Advanced→Proceed" de\n')
        app.run(host='0.0.0.0', port=7861, debug=False,
                ssl_context=(cert, key))
    else:
        print(f'\n  ⚠  HTTP modunda çalışıyor  →  http://{ip}:7861')
        print(f'  Kamera için pip install cryptography gerekli\n')
        app.run(host='0.0.0.0', port=7861, debug=False)
