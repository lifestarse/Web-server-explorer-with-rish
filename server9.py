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
            
            const item = document.createElement('div');
            item.className = 'file-item';
            item.style.borderLeft = isDir ? "4px solid #a8c7fa" : "4px solid transparent";
            
            item.innerHTML = `
                <div class="file-icon">${isDir ? '📁' : '📄'}</div>
                <div class="file-info">
                    <span class="file-name" style="font-weight:bold;">${name}</span>
                    <span class="file-meta" style="color:#8e918f; font-size:11px;">/${cleanPath}</span>
                </div>
                <div style="display: flex; gap: 15px; align-items: center;">
                    <span onclick="event.stopPropagation(); window.location.href='/view/${cleanPath}'" 
                          title="Перейти в папку" style="cursor:pointer; font-size:20px;">🎯</span>
                    <a href="/get/${cleanPath}" onclick="event.stopPropagation()" 
                       style="text-decoration:none; font-size:18px;">⬇️</a>
                </div>
            `;

            // При клике на строку открываем файл или входим в папку
            item.onclick = () => openSmart(cleanPath, isDir);
            list.appendChild(item);
        });
        
        status.innerText = `✅ Найдено элементов: ${d.results.length}`;
        status.style.color = "#c4eed0";

    } catch(err) {
        status.innerText = "💥 Ошибка сервера";
        list.innerHTML = '<div style="padding:20px; text-align:center; color:#f44336;">Ошибка при выполнении запроса</div>';
        console.error(err);
    }
}
     </script>
</body>
</html>
'''

# Помощник для проверки защищенных путей
def is_protected_path(path):
    protected_zones = ["/sdcard/Android", "/storage/emulated/0/Android", "Android/data", "Android/obb"]
    return any(zone in path for zone in protected_zones)

@app.route('/')
@app.route('/view/')
@app.route('/view/<path:subpath>')
@requires_auth
def index(subpath=""):
    subpath = subpath.strip("/")
    full_path = os.path.join(BASE_DIR, subpath)
    items = []
    
 # 1. Сбор файлов (Rish для Android, Python для остального)
    if is_protected_path(full_path):
        # Добавляем 2>/dev/null прямо в команду rish, чтобы подавить системные ошибки линковщика
        output = run_rish(f"ls -1F '{full_path}' 2>/dev/null")
        
        if "ERROR:" in output or "status 1" in output:
            items = [{'name': '⚠️ Ошибка Доступа (Shizuku выключен)', 'is_dir': False}]
        else:
            # ФИЛЬТР: убираем пустые строки, системные ошибки и варнинги линковщика
            lines = [l.strip() for l in output.splitlines() 
                     if l.strip() and "ls:" not in l and "WARNING" not in l and "linker" not in l]
            for l in lines:
                is_dir = l.endswith('/')
                items.append({'name': l.rstrip('/'), 'is_dir': is_dir})
    else:
        try:
            for entry in os.scandir(full_path):
                items.append({'name': entry.name, 'is_dir': entry.is_dir()})
        except:
            items.append({'name': 'Доступ ограничен', 'is_dir': False})

    items.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
    # 2. ГЕНЕРАЦИЯ ХЛЕБНЫХ КРОШЕК (Кликабельный путь)
    breadcrumbs = []
    accumulated_path = ""
    if subpath:
        for part in subpath.split("/"):
            if part:
                accumulated_path = os.path.join(accumulated_path, part).strip("/")
                breadcrumbs.append({'name': part, 'url': accumulated_path})

    # 3. Отправка в шаблон
    return render_template_string(
        HTML_TEMPLATE, 
        items=items, 
        path=subpath, 
        breadcrumbs=breadcrumbs,  # <-- Передаем кликабельные части
        parent_path=os.path.dirname(subpath)
    )
@app.route('/get_sys')
@requires_auth
def get_sys():
    model = run_rish("getprop ro.product.model").strip()
    
    # 1. Получаем весь блок данных о батарее
    batt_data = run_rish("dumpsys battery")
    battery = "N/A"
    
    # 2. Ищем строку, где написано именно "level: число"
    for line in batt_data.splitlines():
        if "level:" in line:
            # Разбиваем по двоеточию и забираем правую часть
            battery = line.split(":")[-1].strip()
            break 
    
    # 3. Получаем память
    mem_raw = run_rish("free -m | grep Mem")
    mem_info = "N/A"
    if mem_raw:
        parts = mem_raw.split()
        if len(parts) >= 3:
            mem_info = f"{parts[2]}MB / {parts[1]}MB"
        
    return jsonify({
        "model": model, 
        "battery": battery + "%", 
        "memory": mem_info
    })
@app.route('/get/<path:f_path>')
@requires_auth
def get_file(f_path):
    f_path = f_path.rstrip('*')
    full_target = os.path.join(BASE_DIR, f_path)

    # Если файл в защищенной зоне — тянем через rish
    if is_protected_path(full_target):
        try:
            # Используем cat через rish
            cmd = f"rish -c 'cat \"{full_target}\"'"
            file_data = subprocess.check_output(cmd, shell=True, timeout=15)
            return send_file(
                io.BytesIO(file_data),
                mimetype='application/octet-stream',
                as_attachment=True,
                download_name=os.path.basename(f_path)
            )
        except Exception as e:
            return f"Ошибка Shizuku (возможно, сервис выключен): {str(e)}", 500

    # Обычный файл — отдаем мгновенно
    if os.path.exists(full_target):
        return send_file(full_target)
    
    return "Файл не найден", 404
@app.route('/save', methods=['POST'])
@requires_auth
def save_file():
    data = request.get_json()
    f_path = data.get('path').strip("/")
    content = data.get('content')
    full_target = os.path.join(BASE_DIR, f_path)

    try:
        if is_protected_path(full_target):
            # Сохраняем через временный файл и rish
            tmp_path = os.path.join("/sdcard/.termux_transfer_buffer", "save_tmp.txt")
            with open(tmp_path, "w", encoding='utf-8') as f:
                f.write(content)
            
            cmd = f'rish -c "cp \'{tmp_path}\' \'{full_target}\' && chmod 666 \'{full_target}\' && rm \'{tmp_path}\'"'
            subprocess.run(cmd, shell=True, check=True)
        else:
            # Обычное сохранение
            with open(full_target, "w", encoding='utf-8') as f:
                f.write(content)
        return jsonify({"status": "success", "msg": "Файл сохранен!"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500
TERMUX_HOME = "/data/data/com.termux/files/home"
current_terminal_cwd = TERMUX_HOME

@app.route('/term', methods=['POST'])
@requires_auth
def terminal():
    global current_terminal_cwd
    data = request.get_json()
    cmd = data.get('cmd', '').strip()
    if not cmd: return jsonify({"out": ""})
    
    try:
        # 1. Обработка смены директории (cd)
        if cmd.startswith("cd "):
            target = cmd[3:].strip()
            if target == "~" or target == "":
                new_path = TERMUX_HOME
            else:
                new_path = os.path.normpath(os.path.join(current_terminal_cwd, target))
            
            # Разрешаем переход: Python может не видеть папки в Android/data, 
            # поэтому для Android путей пропускаем проверку os.path.exists
            if "Android" in new_path or os.path.exists(new_path):
                current_terminal_cwd = new_path
                return jsonify({"out": f"Moved to: {current_terminal_cwd}\n"})
            else:
                return jsonify({"out": f"cd: {target}: No such directory\n"})

        # 2. Умный выбор: rish только если мы в зоне Android
        if "Android" in current_terminal_cwd:
            final_cmd = f'rish -c "{cmd}"'
            # В rish-режиме cwd обычно игнорируется, поэтому путь лучше передавать в самой команде
            # но для стабильности оставим выполнение из корня
            exec_cwd = "/" 
        else:
            final_cmd = cmd
            exec_cwd = current_terminal_cwd

        result = subprocess.check_output(final_cmd, shell=True, stderr=subprocess.STDOUT, cwd=exec_cwd)
        return jsonify({"out": result.decode('utf-8', errors='ignore')})

    except subprocess.CalledProcessError as e:
        return jsonify({"out": e.output.decode('utf-8', errors='ignore')})
    except Exception as e:
        return jsonify({"out": f"Ошибка: {str(e)}"})

@app.route('/upload', methods=['POST'])
@requires_auth
def upload():
    # Получаем путь из формы (в твоем HTML это 'current_path')
    target_dir = request.form.get('current_path', '').strip("/")
    full_target_dir = os.path.join(BASE_DIR, target_dir)
    uploaded_files = request.files.getlist('files')
    
    # Rish нужен только для Android папок
    use_rish = "Android" in full_target_dir

    for f in uploaded_files:
        if f.filename:
            final_path = os.path.join(full_target_dir, f.filename)
            
            if use_rish:
                # Работаем через публичный буфер на SD-карте
                public_buffer = "/sdcard/.termux_transfer_buffer"
                if not os.path.exists(public_buffer): os.makedirs(public_buffer, exist_ok=True)
                
                tmp_path = os.path.join(public_buffer, f.filename)
                f.save(tmp_path)
                
                # Перемещаем/копируем через rish
                cmd = f'rish -c "cp \'{tmp_path}\' \'{final_path}\' && chmod 666 \'{final_path}\' && rm \'{tmp_path}\'"'
                subprocess.run(cmd, shell=True)
            else:
                # Обычное быстрое сохранение напрямую (для Home, Download и т.д.)
                f.save(final_path)
                print(f"Direct upload to: {final_path}")
                
    return redirect(url_for('index', subpath=target_dir))
@app.route('/install_apk', methods=['POST'])
@requires_auth
def install_apk():
    # Пути
    termux_path = "/sdcard/download/installer_cache.apk"
    system_path = "/data/local/tmp/installer_cache.apk"
    
    try:
        f = request.files.get('file')
        if not f: return jsonify({"msg": "❌ Файл не выбран"})

        print(f"--> [1/4] Загрузка файла...")
        f.save(termux_path)
        
        # Перенос и права через rish
        print(f"--> [2/4] Подготовка в /data/local/tmp/...")
        subprocess.run(f'rish -c "cp {termux_path} {system_path} && chmod 644 {system_path}"', shell=True, check=True)

        # Установка
        print(f"--> [3/4] Установка через Shizuku...")
        install_cmd = f'rish -c "pm install -r -t -g {system_path}"'
        res = subprocess.run(install_cmd, shell=True, capture_output=True, text=True, timeout=180)
        
        # Логируем для отладки
        full_log = (res.stdout + res.stderr).strip()
        print(f"STDOUT: {res.stdout}")
        print(f"STDERR: {res.stderr}")

        # Шаг 5: Уборка
        subprocess.run(f'rish -c "rm {system_path}"', shell=True)
        if os.path.exists(termux_path): os.remove(termux_path)

        # ГЛАВНОЕ: Проверяем наличие Success в любом месте вывода
        if "Success" in full_log:
            return jsonify({"msg": "✅ Успешно установлено!"})
        else:
            return jsonify({"msg": f"❌ Ошибка системы: {full_log if full_log else 'Неизвестный сбой'}"})

    except Exception as e:
        print(f"!!! CRASH: {e}")
        return jsonify({"msg": f"💥 Сбой сервера: {str(e)}"})
@app.route('/deep_search')
@requires_auth
def search_api():
    query = request.args.get('q', '')
    if not query: return jsonify({"results": []})
    
    # Ищем прямо в /sdcard/, но так, чтобы find выдавал относительные пути
    # Команда 'cd /sdcard && find . ...' заставляет результаты начинаться с ./
    cmd = f'rish -c "cd /sdcard && find . -iname \'*{query}*\' -exec ls -dF {{}} + 2>/dev/null"'
    
    try:
        res = subprocess.check_output(cmd, shell=True, text=True, timeout=30)
        raw_results = [line.strip() for line in res.split('\n') if line.strip()]
        
        unique_results = []
        seen = set()
        
        for path in raw_results:
            # Убираем префикс ./ который добавляет find
            p = path.lstrip('./')
            
            if p and p not in seen:
                seen.add(p)
                unique_results.append(p)
            
        return jsonify({"results": unique_results})
    except Exception:
        return jsonify({"results": []})
        
@app.route('/download_multi', methods=['POST'])
@requires_auth
def download_multi():
    paths = json.loads(request.form.get('paths', '[]'))
    memory_file = io.BytesIO()
    
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            f_full = os.path.join(BASE_DIR, p)
            if "Android" in f_full:
                # Извлекаем из защищенной папки во временную через rish
                f_tmp = os.path.join("/sdcard/.termux_transfer_buffer", "zip_" + os.path.basename(p))
                subprocess.run(f'rish -c "cp \'{f_full}\' \'{f_tmp}\' && chmod 666 \'{f_tmp}\'"', shell=True)
                if os.path.exists(f_tmp):
                    zf.write(f_tmp, os.path.basename(p))
                    os.remove(f_tmp)
            else:
                # Обычный файл — пакуем напрямую
                if os.path.exists(f_full):
                    zf.write(f_full, os.path.basename(p))
                
    memory_file.seek(0)
    return send_file(memory_file, download_name="archive.zip", as_attachment=True)

if __name__ == "__main__":
    ip = get_ip()
    port = CONF.get("port", 5000)
    print(f"\n🚀 SERVER ACTIVE: http://{ip}:5000\n")
    qr = qrcode.QRCode(box_size=1, border=2)
    qr.add_data(f"http://{ip}:{port}")
    qr.print_ascii()
    app.run(host='0.0.0.0', port=port, debug=False)