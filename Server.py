import os, sys, subprocess, io, zipfile, socket, json, shutil
from functools import wraps
def load_config():
    # Ищет конфиг в папке, где ты находишься в терминале (CWD)
    config_path = os.path.join(os.getcwd(), "server_config.json")
    default_config = {
        "user": "admin",
        "pass": "123",
        "port": 5000
    }
    
    if not os.path.exists(config_path):
        try:
            with open(config_path, "w") as f:
                json.dump(default_config, f, indent=4)
        except:
            # Если в папке нет прав на запись, создаст в корне Termux как бэкап
            config_path = os.path.join(TERMUX_HOME, "server_config.json")
            if not os.path.exists(config_path):
                with open(config_path, "w") as f: json.dump(default_config, f, indent=4)
        return default_config
    with open(config_path, "r") as f:
        return json.load(f)
CONF = load_config()
# --- 1. ПОДГОТОВКА И БИБЛИОТЕКИ ---
def install_deps():
    # 1. Проверка Python библиотек
    required = {'flask', 'pillow', 'qrcode'}
    try:
        # Используем более надежный способ проверки модулей
        import pkg_resources
        installed = {pkg.key for pkg in pkg_resources.working_set}
    except ImportError:
        installed = set()

    missing = required - installed
    if missing:
        print(f"📦 Установка недостающих библиотек: {missing}")
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', *missing])
        except:
            print("⚠️ Не удалось установить через pip автоматически.")

    # 2. Проверка системного rish через встроенный shutil (не требует внешней утилиты which)
    import shutil
    rish_path = shutil.which('rish')
    
    if not rish_path:
        print("🚀 rish не найден. Запускаю установку Shizuku API...")
        try:
            # Убеждаемся, что curl на месте
            if not shutil.which('curl'):
                print("📥 Установка curl...")
                subprocess.run(['pkg', 'install', 'curl', '-y'], check=True)
            
            # Запуск инсталлятора rish
            os.system("bash <(curl -fsSL https://bit.ly/rish3266)")
            print("✅ Процесс установки rish завершен.")
        except Exception as e:
            print(f"❌ Ошибка установки rish: {e}")

# Вызываем исправленную функцию
install_deps()

from flask import Flask, send_file, render_template_string, request, redirect, url_for, Response, jsonify
import qrcode

# --- 2. ЯДРО RISH (SYSTEM BRIDGE) ---
TMP_DIR = "/data/data/com.termux/files/home/tmp_apk"
os.makedirs(TMP_DIR, exist_ok=True)

PM_TMP = "/data/local/tmp"
os.makedirs(TMP_DIR, exist_ok=True)

def run_rish(cmd):
    try:
        # Убираем захват stderr, чтобы системный мусор не шел в результат
        return subprocess.check_output(f"rish -c '{cmd}'", shell=True, timeout=7).decode('utf-8', errors='ignore')
    except Exception as e: return f"ERROR: {str(e)}"

# --- 3. НАСТРОЙКИ ---
app = Flask(__name__)
BASE_DIR = "/sdcard" 
def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close()
        return ip
    except: return "127.0.0.1"

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not (auth.username == CONF["user"] and auth.password == CONF["pass"]):
            return Response('Вход воспрещен!', 401, {'WWW-Authenticate': 'Basic realm="Login"'})
        return f(*args, **kwargs)
    return decorated

# --- 4. ИНТЕРФЕЙС (ULTRA UI) ---
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Termux Rish Explorer</title>
 <style>
    :root {
        --bg: #1f1f1f; /* Темная тема Google */
        --surface: #2d2d2d;
        --primary: #a8c7fa; /* Голубой акцент Google */
        --secondary: #c2e7ff;
        --text: #e3e3e3;
        --text-sub: #8e918f;
    }
    body { font-family: 'Roboto', sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 0; }
    .container { max-width: 800px; margin: auto; padding: 16px; }
    
    /* Системная панель как "Чипсы" */
    .sys-chip { background: var(--surface); border-radius: 16px; padding: 12px 20px; display: flex; justify-content: space-around; margin-bottom: 20px; font-size: 13px; border: 1px solid #444; }
    
    /* Хлебные крошки */
    .path-bar { background: var(--bg); padding: 10px 0; overflow-x: auto; white-space: nowrap; font-size: 14px; margin-bottom: 10px; }
    .path-bar a { color: var(--primary); text-decoration: none; font-weight: 500; }
    
    /* Секции (Карточки) */
    .card { background: var(--surface); border-radius: 24px; padding: 20px; margin-bottom: 16px; box-shadow: 0 2px 6px rgba(0,0,0,0.2); }
    .card-title { font-size: 14px; font-weight: 500; color: var(--primary); margin-bottom: 15px; display: block; }
    
    /* Кнопки в стиле Material */
    .btn { border: none; padding: 10px 20px; border-radius: 20px; cursor: pointer; font-weight: 500; font-size: 14px; transition: 0.2s; display: inline-flex; align-items: center; gap: 8px; }
    .btn-blue { background: var(--primary); color: #062e6f; }
    .btn-green { background: #c4eed0; color: #072711; }
    .btn-outline { background: transparent; border: 1px solid #8e918f; color: var(--primary); }
    .btn:hover { opacity: 0.9; transform: translateY(-1px); }

    /* Список файлов как в Files by Google */
    .file-list { background: var(--surface); border-radius: 24px; overflow: hidden; }
    .file-item { display: flex; align-items: center; padding: 16px; border-bottom: 1px solid #3c3c3c; cursor: pointer; transition: 0.2s; }
    .file-item:hover { background: #353535; }
    .file-icon { width: 40px; height: 40px; background: #3d3d3d; border-radius: 12px; display: flex; align-items: center; justify-content: center; margin-right: 16px; font-size: 20px; }
    .file-info { flex-grow: 1; display: flex; flex-direction: column; }
    .file-name { font-size: 15px; font-weight: 400; color: #e3e3e3; }
    .file-meta { font-size: 12px; color: var(--text-sub); }
    
    /* Терминал - компактный */
    #tOut { background: #000; border-radius: 16px; padding: 15px; height: 200px; font-family: 'Monaco', monospace; font-size: 12px; border: 1px solid #333; }
    
    /* Модалки */
    .modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.8); z-index: 100; align-items: center; justify-content: center; padding: 20px; }
    .modal-content { background: var(--surface); border-radius: 28px; width: 100%; max-width: 600px; padding: 24px; position: relative; }
</style>
</head>
<body>
    <div id="imgM" class="modal" onclick="closeM()"><span class="close-btn">❌</span><img id="imgV" class="modal-content"></div>
    <div id="vidM" class="modal"><span class="close-btn" onclick="closeM()">❌</span><video id="vidV" class="modal-content" controls autoplay></video></div>
    <div id="txtM" class="modal">
        <span class="close-btn" onclick="closeM()">❌</span>
        <div style="width: 90%; height: 85%; display: flex; flex-direction: column; gap: 10px; align-items: center;">
            <div id="txtPath" style="color: #aaa; font-size: 12px; font-family: monospace;"></div>
            <textarea id="txtV" class="text-view"></textarea>
            <button class="btn btn-green" onclick="saveCurrentFile()" id="saveBtn">💾 Сохранить изменения</button>
        </div>
    </div>

    <div class="container">
        <div class="sys-chip">
            <span>📱 <b id="sysModel">...</b></span>
            <span>🔋 <b id="sysBatt">...</b></span>
            <span>🧠 <b id="sysMem">...</b></span>
        </div>

        <div class="path-bar">
            <a href="/view/">Внутренняя память</a>
            {% for crumb in breadcrumbs %}
                <span style="color: var(--text-sub);"> › </span>
                <a href="/view/{{ crumb.url }}">{{ crumb.name }}</a>
            {% endfor %}
        </div>

        <div class="card">
            <span class="card-title">Инструменты</span>
            <div style="display: flex; flex-wrap: wrap; gap: 10px;">
                <button class="btn btn-blue" onclick="document.getElementById('apkInput').click()">📦 APK</button>
                <button class="btn btn-outline" onclick="location.href='/view/{{ parent_path }}'">⬅️ Назад</button>
                <button class="btn btn-green" onclick="document.getElementById('fileInp').click()">➕ Файл</button>
                <button class="btn btn-outline" onclick="toggleAll()">✅ Все</button>
                <button class="btn btn-blue" id="zBtn" onclick="dlZip()" disabled>📥 ZIP (0)</button>
                
                <input type="file" id="apkInput" accept=".apk" style="display: none;" onchange="handleApk(this)">
                <form action="/upload" method="post" enctype="multipart/form-data" id="upForm" style="display:none">
                    <input type="hidden" name="current_path" value="{{ path }}">
                    <input type="file" name="files" id="fileInp" multiple onchange="document.getElementById('upForm').submit()">
                </form>
            </div>
            <div id="apkStatus" style="margin-top: 10px; font-size: 12px; color: var(--primary);"></div>
        </div>
<div class="card" style="padding: 10px 20px; border-radius: 30px; margin-bottom: 15px; display: flex; align-items: center; gap: 10px;">
    <span style="font-size: 18px;">🔍</span>
    <input type="text" id="searchInput" placeholder="Поиск в этой папке..." 
           style="flex-grow: 1; background: transparent; border: none; color: #fff; outline: none; font-size: 15px;"
           oninput="localSearch()">
    <button class="btn btn-outline" style="padding: 5px 15px; font-size: 12px;" onclick="deepSearch()">Везде (rish)</button>
</div>
        <div class="file-list" id="fileList">
            {% for item in items %}
            <div class="file-item">
                <input type="checkbox" class="file-check" 
                       data-path="{{ (path + '/' + item.name).strip('/') }}" 
                       style="width: 20px; height: 20px; margin-right: 15px; accent-color: var(--primary);">
                
                <div class="file-icon" onclick="openSmart('{{ (path + '/' + item.name).strip('/') }}', {{ 'true' if item.is_dir else 'false' }})">
                    {{ "📁" if item.is_dir else "📄" }}
                </div>
                
                <div class="file-info" onclick="openSmart('{{ (path + '/' + item.name).strip('/') }}', {{ 'true' if item.is_dir else 'false' }})">
                    <span class="file-name">{{ item.name }}</span>
                    <span class="file-meta">{{ "Папка" if item.is_dir else "Файл" }}</span>
                </div>
                
                <div style="display: flex; gap: 15px; align-items: center;">
                    <a href="/get/{{ (path + '/' + item.name).strip('/') }}" style="text-decoration:none; font-size: 18px;">⬇️</a>
                    <span onclick="delItem('{{ (path + '/' + item.name).strip('/') }}')" style="cursor:pointer; font-size: 18px;">🗑️</span>
                </div>
            </div>
            {% endfor %}
        </div>

        <div class="card" style="margin-top: 24px;">
            <span class="card-title">Терминал Termux</span>
            <div id="tOut">$ Ready...</div>
            <div style="display: flex; align-items: center; border-bottom: 1px solid #444; margin-top: 10px;">
                <span style="color: var(--primary); padding-right: 10px;">$</span>
                <input type="text" id="tInp" placeholder="Команда..." style="flex-grow: 1; background:transparent; border:none; color:#fff; padding:12px 0; outline:none; font-family: monospace;">
            </div>
        </div>
    </div>

<script>
async function handleApk(input) {
    const file = input.files[0];
    if (!file) return;

    const status = document.getElementById('apkStatus');
    status.style.color = "#ff9800";
    status.innerText = `⏳ Установка ${file.name}... Подождите.`;
    
    console.log("🚀 Файл выбран:", file.name, "Размер:", file.size);
    
    const formData = new FormData();
    formData.append('file', file);

    try {
        const r = await fetch('/install_apk', { method: 'POST', body: formData });
        
        // Проверка: если сервер вернул ошибку (не 200)
        if (!r.ok) {
            const errorText = await r.text();
            throw new Error(`Сервер вернул код ${r.status}: ${errorText}`);
        }

        const d = await r.json();
        console.log("✅ Ответ сервера:", d);
        
        status.innerText = d.msg;
        status.style.color = d.msg.includes('✅') ? "#4caf50" : "#f44336";
    } catch(err) {
        console.error("❌ Ошибка выполнения:", err);
        status.style.color = "#f44336";
        status.innerText = "❌ " + (err.message || "Ошибка связи");
    } finally {
        input.value = ""; // В любом случае сбрасываем инпут
    }
}
// Авто-обновление системной инфы
async function updateSys() {
    try {
        const r = await fetch('/get_sys');
        const d = await r.json();
        document.getElementById('sysModel').innerText = d.model;
        document.getElementById('sysBatt').innerText = d.battery;
        document.getElementById('sysMem').innerText = d.memory;
    } catch(e) {}
}
setInterval(updateSys, 10000); // Обновлять каждые 10 сек
updateSys();
    async function runCmd() {
        const i = document.getElementById('tInp');
        const o = document.getElementById('tOut');
        const cmd = i.value;
        if(!cmd) return;

        o.innerText += `\n$ ${cmd}\n`;
        i.value = '';

        const r = await fetch('/term', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({cmd: cmd})
        });
        const d = await r.json();
        o.innerText += d.out;
        o.scrollTop = o.scrollHeight;
    }

    document.getElementById('tInp').addEventListener('keypress', e => { if(e.key === 'Enter') runCmd(); });
    let currentEditPath = "";

// Обновляем функцию открытия, чтобы она записывала путь
function openSmart(path, isDir) {
    if (isDir) { window.location.href = '/view/' + path; return; }
    const ext = path.split('.').pop().toLowerCase();
    const url = '/get/' + path;
    currentEditPath = path;

    if (['jpg','jpeg','png','gif','webp'].includes(ext)) {
        document.getElementById('imgV').src = url; document.getElementById('imgM').style.display = 'flex';
    } else if (['mp4','mkv','webm','mov'].includes(ext)) {
        document.getElementById('vidV').src = url; document.getElementById('vidM').style.display = 'flex';
    } else if (['txt','log','json','dat','py','sh','ini','xml','cfg','conf'].includes(ext)) {
        document.getElementById('txtPath').innerText = path;
        fetch(url).then(r => r.text()).then(t => {
            document.getElementById('txtV').value = t; // Используем .value для textarea
            document.getElementById('txtM').style.display = 'flex';
        });
    } else { window.open(url, '_blank'); }
}

async function saveCurrentFile() {
    const btn = document.getElementById('saveBtn');
    const content = document.getElementById('txtV').value;
    btn.disabled = true; btn.innerText = "⌛ Сохранение...";

    const r = await fetch('/save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: currentEditPath, content: content})
    });
    const d = await r.json();
    alert(d.msg);
    btn.disabled = false; btn.innerText = "💾 Сохранить изменения";
}
</script>
   </div>

    <script>
        function openSmart(path, isDir) {
            if (isDir) { window.location.href = '/view/' + path; return; }
            const ext = path.split('.').pop().toLowerCase();
            const url = '/get/' + path;
            if (['jpg','jpeg','png','gif','webp'].includes(ext)) {
                document.getElementById('imgV').src = url; document.getElementById('imgM').style.display = 'flex';
            } else if (['mp4','mkv','webm','mov'].includes(ext)) {
                document.getElementById('vidV').src = url; document.getElementById('vidM').style.display = 'flex';
            } else if (['txt','log','json','dat','py','sh','ini','xml'].includes(ext)) {
                fetch(url).then(r => r.text()).then(t => {
                    document.getElementById('txtV').innerText = t; document.getElementById('txtM').style.display = 'flex';
                });
            } else { window.open(url, '_blank'); }
        }

        function closeM() {
            document.querySelectorAll('.modal').forEach(m => m.style.display = 'none');
            document.getElementById('vidV').pause(); document.getElementById('vidV').src = "";
        }

        function toggleAll() {
            let cbs = document.querySelectorAll('.file-check');
            let s = !cbs[0].checked; cbs.forEach(c => c.checked = s); updateBtn();
        }

        function updateBtn() {
            const n = Array.from(document.querySelectorAll('.file-check:checked')).length;
            document.getElementById('zBtn').disabled = n === 0;
            document.getElementById('zBtn').innerText = `📥 ZIP (${n})`;
        }

        document.addEventListener('change', e => { if(e.target.classList.contains('file-check')) updateBtn(); });

        function dlZip() {
            const paths = Array.from(document.querySelectorAll('.file-check:checked')).map(c => c.dataset.path);
            const form = document.createElement('form'); form.method = 'POST'; form.action = '/download_multi';
            const input = document.createElement('input'); input.type = 'hidden'; input.name = 'paths'; input.value = JSON.stringify(paths);
            form.appendChild(input); document.body.appendChild(form); form.submit();
        }

        function delItem(path) { if(confirm('Удалить через rish?')) window.location.href='/delete/'+path; }
   // Быстрый фильтр по текущей странице
function localSearch() {
    const query = document.getElementById('searchInput').value.toLowerCase();
    const items = document.querySelectorAll('.file-item');
    
    items.forEach(item => {
        const name = item.querySelector('.file-name').innerText.toLowerCase();
        if (name.includes(query)) {
            item.style.display = 'flex';
        } else {
            item.style.display = 'none';
        }
    });
}

async function deepSearch() {
    const query = document.getElementById('searchInput').value;
    if (!query) return alert("Введите текст для поиска");
    
    const status = document.getElementById('apkStatus');
    const list = document.getElementById('fileList');
    
    // Визуальный отклик
    status.innerText = "⌛ Глубокое сканирование...";
    status.style.color = "#a8c7fa";
    list.innerHTML = `
        <div style="padding:40px; text-align:center;">
            <div class="spinner" style="margin-bottom:10px;">🚀</div>
            Ищу "${query}" во всех закоулках системы...
        </div>`;
    
    try {
        const r = await fetch(`/deep_search?q=${encodeURIComponent(query)}`);
        const d = await r.json();
        
        list.innerHTML = ""; // Очистка экрана

        if (!d.results || d.results.length === 0) {
            status.innerText = "❌ Ничего не найдено";
            list.innerHTML = '<div style="padding:20px; text-align:center;">Файлы не найдены</div>';
            return;
        }

        d.results.forEach(pathWithMark => {
            // Если в конце '/', значит это папка (благодаря ls -dF)
            const isDir = pathWithMark.endsWith('/');
            // Внутри цикла d.results.forEach
            const cleanPath = isDir ? pathWithMark.slice(0, -1) : pathWithMark;
            const parts = cleanPath.split('/');
            const name = parts[parts.length - 1];
