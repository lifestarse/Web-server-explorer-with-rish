import os, sys, subprocess, io, zipfile, socket, json, shutil, time, importlib.util
from functools import wraps

TERMUX_HOME = "/data/data/com.termux/files/home"
def check_env():
    print("\n🔍 Проверка окружения...")
    
    # 1. Проверка памяти
    if not os.path.exists("/sdcard"):
        print("⚠️ ПРЕДУПРЕЖДЕНИЕ: Нет доступа к /sdcard. Выполни 'termux-setup-storage'")
    else:
        print("✅ Доступ к /sdcard есть.")

    # 2. Мягкая проверка rish (теперь не уронит скрипт)
    try:
        # Пытаемся запустить через shell, это надежнее в Termux
        res = subprocess.run('rish -c "whoami"', shell=True, capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            print(f"✅ Shizuku активен (пользователь: {res.stdout.strip()})")
        else:
            print("⚠️ Shizuku (rish) найден, но вернул ошибку. Проверь статус в приложении Shizuku.")
    except Exception:
        print("ℹ️ Shizuku (rish) не настроен. Функции Android/data будут недоступны.")

    # 3. Проверка папки буфера
    buffer_path = "/sdcard/.termux_transfer_buffer"
    if not os.path.exists(buffer_path):
        try:
            os.makedirs(buffer_path, exist_ok=True)
            print(f"✅ Папка буфера создана: {buffer_path}")
        except:
            print(f"⚠️ Не удалось создать {buffer_path}. Проверь права записи.")
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
CLIPBOARD = {"path": None, "mode": "copy"} 
# --- 1. ПОДГОТОВКА И БИБЛИОТЕКИ ---
def install_deps():
    # 1. Проверка и установка Python библиотек
    # Заменил 'pillow' на 'Pillow' (регистр важен для pip)
    required = {'flask': 'flask', 'Pillow': 'PIL', 'qrcode': 'qrcode'}
    
    missing = []
    for package_name, import_name in required.items():
        if importlib.util.find_spec(import_name) is None:
            missing.append(package_name)

    if missing:
        print(f"📦 Установка недостающих библиотек: {', '.join(missing)}...")
        try:
            # Используем -m pip для гарантии установки в текущий интерпретатор
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
            print("✅ Библиотеки успешно установлены.")
        except Exception as e:
            print(f"⚠️ Ошибка автоматической установки через pip: {e}")
            print("Попробуйте вручную: pip install flask qrcode Pillow")

    # 2. Проверка и установка rish (Shizuku)
    if not shutil.which('rish'):
        print("\n🚀 rish (Shizuku API) не найден.")
        
        # Спрашиваем пользователя, хочет ли он установить rish
        # (Важно, так как установка требует интернета и curl)
        choice = input("Установить rish автоматически? (y/n): ").lower()
        if choice == 'y':
            try:
                if not shutil.which('curl'):
                    print("📥 Установка curl через pkg...")
                    subprocess.run(['pkg', 'install', 'curl', '-y'], check=True)
                
                print("⏳ Запуск скрипта установки rish...")
                # Используем прямой вызов curl + bash
                os.system("curl -fsSL https://raw.githubusercontent.com/rish-sh/rish/main/install.sh | sh")
                print("✅ Процесс установки rish завершен. Перезапустите сервер, если rish не подхватился.")
            except Exception as e:
                print(f"❌ Не удалось установить rish: {e}")
        else:
            print("⏭️ Пропускаем установку rish. Функции Android/data будут недоступны.")

# Вызываем в самом начале, до остальных импортов
install_deps()
from flask import Flask, send_file, render_template_string, request, redirect, url_for, Response, jsonify
import qrcode

# --- 2. ЯДРО RISH (SYSTEM BRIDGE) ---
TMP_DIR = "/data/data/com.termux/files/home/tmp_apk"
os.makedirs(TMP_DIR, exist_ok=True)
if not os.path.exists("/sdcard/.termux_transfer_buffer"):
    os.makedirs("/sdcard/.termux_transfer_buffer", exist_ok=True)
    
PM_TMP = "/data/local/tmp"
os.makedirs(TMP_DIR, exist_ok=True)

def run_rish(cmd):
    try:
        # Убрали timeout=7, теперь команда может работать хоть час
        return subprocess.check_output(f"rish -c '{cmd}'", shell=True).decode('utf-8', errors='ignore')
    except Exception as e: 
        return f"ERROR: {str(e)}"


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
    .file-info {
    flex-grow: 1;             /* Занимает всё свободное место */
    min-width: 0;             /* КРИТИЧЕСКИ ВАЖНО для работы ellipsis во flex */
    display: flex;
    flex-direction: column;
    margin-right: 10px;       /* Отступ от иконок действий */}
    .file-name {
    font-size: 15px;
    font-weight: 400;
    color: #e3e3e3;
    /* Фикс длинных названий */
    white-space: nowrap;      /* Запрещаем перенос на новую строку */
    overflow: hidden;         /* Прячем то, что не влезло */
    text-overflow: ellipsis;  /* Добавляем три точки (...) */
    max-width: 220px;         /* Ограничиваем ширину (подбери под экран) */
    display: block;}
    .file-meta { font-size: 12px; color: var(--text-sub); }
    /* Увеличиваем контейнер модалки для текста */
#txtM .modal-content {
    width: 95%;
    max-width: 1200px; /* Широкий экран для кода */
    height: 90vh;      /* 90% высоты экрана */
    display: flex;
    flex-direction: column;
}
/* Плавное появление строк списка */
.file-item {
    animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(5px); }
    to { opacity: 1; transform: translateY(0); }
}
/* Настройка самого поля ввода (textarea) */
.text-view {
    width: 100%;
    flex-grow: 1;      /* Занимает всё свободное место в модалке */
    background: #121212;
    color: #00ff41;    /* "Матричный" зеленый или #e3e3e3 */
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 14px;
    padding: 15px;
    border: 1px solid #444;
    border-radius: 12px;
    resize: none;      /* Убираем ручное изменение размера, так как оно на весь экран */
    outline: none;
    line-height: 1.5;
}
.file-item {
    user-select: none;
    -webkit-user-select: none;
    -webkit-touch-callout: none; /* Отключает системное меню на iOS/Android */
}

#contextMenu {
    position: fixed; /* Именно fixed, а не absolute */
    display: none;
    z-index: 10000;
    background: #202124;
    border: 1px solid #3c4043;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.5);
    width: 180px;
    padding: 8px 0;
}

#contextMenu button {
    text-align: left;
    padding: 12px 15px;
    border: none;
    background: transparent;
    color: white;
    width: 100%;
    cursor: pointer;
    display: block;
    font-size: 14px;
}

#contextMenu button:hover {
    background: #333;
}


    /* Терминал - компактный */
    #tOut { background: #000; border-radius: 16px; padding: 15px; height: 200px; font-family: 'Monaco', monospace; font-size: 12px; border: 1px solid #333; }
    
    /* Модалки */
    .modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.8); z-index: 100; align-items: center; justify-content: center; padding: 20px; }
    .modal-content { background: var(--surface); border-radius: 28px; width: 100%; max-width: 600px; padding: 24px; position: relative; }
</style>
</head>
<body>
<div id="contextMenu" style="position: fixed; display: none; z-index: 10000; background: #202124; border: 1px solid #3c4043; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.5); width: 220px; padding: 8px 0;">
    <div id="menuFileName" style="padding: 8px 15px; font-size: 12px; color: #a8c7fa; border-bottom: 1px solid #3c4043; margin-bottom: 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;"></div>
    
    <div onclick="ctxAction('copy')" style="padding: 10px 15px; cursor: pointer; display: flex; align-items: center; gap: 10px;" onmouseover="this.style.background='#303134'" onmouseout="this.style.background='none'">
        <span>📋</span> Копировать
    </div>
<div onclick="createPrompt(true)" style="padding: 10px 15px; cursor: pointer; display: flex; align-items: center; gap: 10px;" onmouseover="this.style.background='#303134'" onmouseout="this.style.background='none'">
    <span>📁+</span> Новая папка
</div>
<div onclick="createPrompt(false)" style="padding: 10px 15px; cursor: pointer; display: flex; align-items: center; gap: 10px;" onmouseover="this.style.background='#303134'" onmouseout="this.style.background='none'">
    <span>📄+</span> Новый файл
</div>
<hr style="border: 0; border-top: 1px solid #3c4043; margin: 5px 0;">

    <div onclick="ctxAction('cut')" style="padding: 10px 15px; cursor: pointer; display: flex; align-items: center; gap: 10px;" onmouseover="this.style.background='#303134'" onmouseout="this.style.background='none'">
        <span>✂️</span> Вырезать
    </div>

    <div onclick="ctxAction('paste')" style="padding: 10px 15px; cursor: pointer; display: flex; align-items: center; gap: 10px;" onmouseover="this.style.background='#303134'" onmouseout="this.style.background='none'">
        <span>📥</span> Вставить сюда
    </div>

    <div onclick="ctxAction('rename')" style="padding: 10px 15px; cursor: pointer; display: flex; align-items: center; gap: 10px;" onmouseover="this.style.background='#303134'" onmouseout="this.style.background='none'">
        <span>✏️</span> Переименовать
    </div>

    <div onclick="ctxAction('copyPath')" style="padding: 10px 15px; cursor: pointer; display: flex; align-items: center; gap: 10px;" onmouseover="this.style.background='#303134'" onmouseout="this.style.background='none'">
        <span>📍</span> Копировать путь
    </div>

    <div onclick="ctxAction('download')" style="padding: 10px 15px; cursor: pointer; display: flex; align-items: center; gap: 10px;" onmouseover="this.style.background='#303134'" onmouseout="this.style.background='none'">
        <span>📂</span> Скачать
    </div>

    <div onclick="ctxAction('delete')" style="padding: 10px 15px; cursor: pointer; display: flex; align-items: center; gap: 10px; color: #f28b82;" onmouseover="this.style.background='#303134'" onmouseout="this.style.background='none'">
        <span>🗑️</span> Удалить
    </div>
</div>




    <div id="imgM" class="modal" onclick="closeM()"><span class="close-btn">❌</span><img id="imgV" class="modal-content"></div>
    <div id="vidM" class="modal"><span class="close-btn" onclick="closeM()">❌</span><video id="vidV" class="modal-content" controls autoplay></video></div>
    <div id="txtM" class="modal">
    <div class="modal-content">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
            <div id="txtPath" style="color: var(--primary); font-size: 12px; font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"></div>
            <span class="close-btn" onclick="closeM()" style="cursor:pointer;">❌</span>
        </div>
        
        <textarea id="txtV" class="text-view" spellcheck="false"></textarea>
        
        <div style="margin-top: 15px; display: flex; gap: 10px;">
            <button class="btn btn-green" onclick="saveCurrentFile()" id="saveBtn" style="flex-grow: 1;">
                💾 Сохранить изменения
            </button>
            <button class="btn btn-outline" onclick="closeM()">Отмена</button>
        </div>
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
                <button class="btn btn-green" onclick="document.getElementById('fileInp').click()">➕ Upload</button>
                <button class="btn btn-outline" onclick="toggleAll()">✅ Все</button>
                <button class="btn btn-blue" id="zBtn" onclick="dlZip()" disabled>📥 ZIP (0)</button>
                <button class="btn btn-outline" onclick="createPrompt(true)">📁+ Папка</button>
        <button class="btn btn-outline" onclick="createPrompt(false)">📄+ Файл</button>
                <button class="btn btn-outline" id="pasteBtn" 
        onclick="ctxAction('paste')" 
        style="{% if clipboard %}display:inline-flex;{% else %}display:none;{% endif %} border-color: #f1c40f; color: #f1c40f;">
    📋 Вставить
</button>


                
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
    <button class="btn btn-outline" style="padding: 5px 15px; font-size: 12px;" onclick="deepSearch()">Global search</button>
</div>
        <div class="file-list" id="fileList">
    {% for item in items %}
    <div class="file-item" 
         data-path="{{ (path + '/' + item.name).strip('/') }}" 
         oncontextmenu="openCtxMenu(event); return false;">
        
        <input type="checkbox" class="file-check" 
               onchange="updateMultiBar()"
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
            {% if not item.is_dir %}
            <a href="/get/{{ (path + '/' + item.name).strip('/') }}" style="text-decoration:none; font-size: 18px;">⬇️</a>
            {% endif %}
        </div>
    </div>
    {% endfor %}
</div>

    </div> <div id="multiBar" style="position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%); background: #a8c7fa; color: #062e6f; padding: 12px 25px; border-radius: 50px; display: none; align-items: center; gap: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); z-index: 9999; min-width: 280px; justify-content: space-between;">
        <span id="multiCount" style="font-weight: bold; font-size: 14px;">Выбрано: 0</span>
        <div style="display: flex; gap: 20px;">
            <button onclick="multiDo('copy')" style="background:none; border:none; cursor:pointer; font-size: 22px;" title="Копировать">📋</button>
            <button onclick="multiDo('cut')" style="background:none; border:none; cursor:pointer; font-size: 22px;" title="Вырезать">✂️</button>
            <button onclick="multiDo('delete')" style="background:none; border:none; cursor:pointer; font-size: 22px;" title="Удалить">🗑️</button>
        </div>
        <button onclick="cancelMulti()" style="background:#062e6f; color:#fff; border:none; border-radius:50%; width:28px; height:28px; cursor:pointer; display: flex; align-items: center; justify-content: center; font-size: 12px;">✕</button>
    </div>

    <div id="imgM" class="modal" onclick="closeM()"><span class="close-btn">❌</span><img id="imgV" class="modal-content"></div>
<script>
function updateMultiBar() {
    const checked = document.querySelectorAll('.file-check:checked');
    const bar = document.getElementById('multiBar');
    const count = document.getElementById('multiCount');
    
    if (checked.length > 0) {
        bar.style.display = 'flex';
        count.innerText = `Выбрано: ${checked.length}`;
    } else {
        bar.style.display = 'none';
    }
}

// Привязываем событие к чекбоксам (вызывать при рендеринге списка)
// Внутри цикла формирования списка файлов в JS добавь:
// <input type="checkbox" class="file-check" onchange="updateMultiBar()" data-path="${item.path}">

async function multiDo(action) {
    const checked = document.querySelectorAll('.file-check:checked');
    const paths = Array.from(checked).map(c => c.dataset.path);
    
    if (action === 'delete' && !confirm(`Удалить ${paths.length} объектов?`)) return;

    const r = await fetch('/multi_action', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ action, paths })
    });

    if (r.ok) {
        if (action === 'delete') {
            location.reload(); // Перезагружаем для обновления списка
        } else {
            showStatus(`✅ ${paths.length} шт. добавлено в буфер`);
            cancelMulti();
        }
    }
}

function cancelMulti() {
    document.querySelectorAll('.file-check').forEach(c => c.checked = false);
    updateMultiBar();
}

function toggleAll() {
    // Находим все чекбоксы файлов на странице
    const cbs = document.querySelectorAll('.file-check');
    // Проверяем, выделены ли уже все. Если да — снимаем, если нет — выделяем.
    const allChecked = Array.from(cbs).every(cb => cb.checked);
    
    cbs.forEach(cb => {
        cb.checked = !allChecked;
    });

    // Обновляем состояние кнопки ZIP
    updateBtn();
    updateMultiBar(); 
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
            Ищу "${query}" по всей системе...
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
            const isDir = pathWithMark.endsWith('/');
            const cleanPath = isDir ? pathWithMark.slice(0, -1) : pathWithMark;
            const name = cleanPath.split('/').pop();
            
            const item = document.createElement('div');
            item.className = 'file-item';
            item.setAttribute('data-path', cleanPath);
            item.style.borderLeft = isDir ? "4px solid #a8c7fa" : "4px solid transparent";
            
            item.innerHTML = `
                <input type="checkbox" class="file-check" data-path="${cleanPath}" style="width: 20px; height: 20px; margin-right: 15px;">
                <div class="file-icon">${isDir ? '📁' : '📄'}</div>
                <div class="file-info">
                    <span class="file-name" style="font-weight:bold;">${name}</span>
                    <span class="file-meta" style="color:#8e918f; font-size:11px;">/${cleanPath}</span>
                </div>
                <div style="display: flex; gap: 15px; align-items: center;">
                    <span onclick="event.stopPropagation(); window.location.href='/view/${encodeURIComponent(cleanPath)}'" 
                          title="Перейти" style="cursor:pointer; font-size:20px;">🎯</span>
                </div>
            `;

            // Клик по строке открывает файл/папку
            item.onclick = () => openSmart(cleanPath, isDir);
            list.appendChild(item);
        });
        
        status.innerText = `✅ Найдено: ${d.results.length}`;
        status.style.color = "#c4eed0";

    } catch(err) {
        status.innerText = "💥 Ошибка сервера";
        list.innerHTML = '<div style="padding:20px; text-align:center; color:#f44336;">Ошибка при поиске</div>';
        console.error(err);
    }
}


// Глобальные переменные
let currentEditPath = "";
let selectedPath = "";
let longPressTimer;
const ctxMenu = document.getElementById('contextMenu');

// --- 1. СИСТЕМА И ИНТЕРФЕЙС ---
async function updateSys() {
    try {
        const r = await fetch('/get_sys');
        const d = await r.json();
        document.getElementById('sysModel').innerText = d.model;
        document.getElementById('sysBatt').innerText = d.battery;
        document.getElementById('sysMem').innerText = d.memory;
    } catch(e) {}
}

function updateBtn() {
    const checked = document.querySelectorAll('.file-check:checked');
    const zBtn = document.getElementById('zBtn');
    if (zBtn) {
        zBtn.disabled = checked.length === 0;
        zBtn.innerText = `📥 ZIP (${checked.length})`;
    }
}

function closeM() {
    document.querySelectorAll('.modal').forEach(m => m.style.display = 'none');
    const vid = document.getElementById('vidV');
    if(vid) { vid.pause(); vid.src = ""; }
}

// --- 2. ФАЙЛОВЫЙ МЕНЕДЖЕР ---
function openSmart(path, isDir) {
    if (isDir) { 
        window.location.href = '/view/' + encodeURIComponent(path); 
        return; 
    }
    
    const ext = path.split('.').pop().toLowerCase();
    const url = '/get/' + encodeURIComponent(path);
    currentEditPath = path;

    if (['jpg','jpeg','png','gif','webp'].includes(ext)) {
        document.getElementById('imgV').src = url; 
        document.getElementById('imgM').style.display = 'flex';
    } else if (['mp4','mkv','webm','mov'].includes(ext)) {
        document.getElementById('vidV').src = url; 
        document.getElementById('vidM').style.display = 'flex';
    } else if (['txt','log','json','dat','py','sh','ini','xml','cfg','conf'].includes(ext)) {
        document.getElementById('txtPath').innerText = path;
        fetch(url).then(r => r.text()).then(t => {
            document.getElementById('txtV').value = t;
            document.getElementById('txtM').style.display = 'flex';
        });
    } else { 
        window.open(url, '_blank'); 
    }
}

async function saveCurrentFile() {
    const btn = document.getElementById('saveBtn');
    const content = document.getElementById('txtV').value;
    btn.disabled = true; btn.innerText = "⌛...";
    const r = await fetch('/save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: currentEditPath, content: content})
    });
    const d = await r.json();
    alert(d.msg);
    btn.disabled = false; btn.innerText = "💾 Сохранить";
}

function dlZip() {
    const paths = Array.from(document.querySelectorAll('.file-check:checked')).map(c => c.dataset.path);
    if (paths.length === 0) return;
    const form = document.createElement('form'); form.method = 'POST'; form.action = '/download_multi';
    const input = document.createElement('input'); input.type = 'hidden'; input.name = 'paths'; input.value = JSON.stringify(paths);
    form.appendChild(input); document.body.appendChild(form); form.submit();
}

function openCtxMenu(e) {
    e.preventDefault();
    const item = e.target.closest('.file-item');
    if (!item) return;

    selectedPath = item.getAttribute('data-path');
    const menuName = document.getElementById('menuFileName');
    if (menuName) menuName.innerText = selectedPath.split('/').pop();
    
    ctxMenu.style.display = 'block';
    
    // Получаем координаты клика
    let x = e.touches ? e.touches[0].clientX : e.clientX;
    let y = e.touches ? e.touches[0].clientY : e.clientY;

    // Размеры самого меню
    const menuWidth = ctxMenu.offsetWidth;
    const menuHeight = ctxMenu.offsetHeight;

    // Размеры окна браузера
    const windowWidth = window.innerWidth;
    const windowHeight = window.innerHeight;

    // Проверка правой границы: если меню не влезает справа, смещаем влево
    if (x + menuWidth > windowWidth) {
        x = windowWidth - menuWidth - 10;
    }

    // Проверка нижней границы: если меню не влезает снизу, открываем его ВВЕРХ
    if (y + menuHeight > windowHeight) {
        y = y - menuHeight;
    }

    ctxMenu.style.left = x + 'px';
    ctxMenu.style.top = y + 'px';
}

async function copyFile(path) {
    const r = await fetch('/copy/' + encodeURIComponent(path));
    if (r.ok) {
        document.getElementById('pasteBtn').style.display = 'inline-flex';
        document.getElementById('apkStatus').innerText = "📋 Скопировано";
    }
}

function delItem(path) { 
    if (confirm('⚠️ Вы уверены, что хотите удалить: ' + path + '?')) {
        showStatus("🗑️ Удаление...");
        
        fetch('/delete/' + encodeURIComponent(path))
            .then(res => {
                if (res.ok) {
                    showStatus("✅ Удалено");
                    location.reload(); // Обновляем список файлов
                } else {
                    alert('Ошибка при удалении. Возможно, нет прав.');
                }
            })
            .catch(err => alert('Ошибка сети: ' + err));
    }
}


// --- 4. APK И ПОИСК ---
async function handleApk(input) {
    const file = input.files[0];
    if (!file) return;
    const status = document.getElementById('apkStatus');
    status.innerText = `⏳ Инсталл ${file.name}...`;
    const formData = new FormData();
    formData.append('file', file);
    try {
        const r = await fetch('/install_apk', { method: 'POST', body: formData });
        const d = await r.json();
        status.innerText = d.msg;
    } catch(e) { status.innerText = "❌ Ошибка"; }
}

function localSearch() {
    const q = document.getElementById('searchInput').value.toLowerCase();
    document.querySelectorAll('.file-item').forEach(it => {
        const name = it.querySelector('.file-name').innerText.toLowerCase();
        it.style.display = name.includes(q) ? 'flex' : 'none';
    });
}
async function cutFile(path) {
    const r = await fetch('/cut/' + encodeURIComponent(path));
    if (r.ok) {
        document.getElementById('pasteBtn').style.display = 'inline-flex';
        showStatus("✂️ Вырезано: " + path.split('/').pop());
        // Опционально: можно визуально приглушить элемент, который вырезали
        document.querySelectorAll('.file-item').forEach(el => el.style.opacity = "1");
        const currentItem = document.querySelector(`.file-item[data-path="${path}"]`);
        if (currentItem) currentItem.style.opacity = "0.5";
    }
}

// Глобальный обработчик контекстного меню
document.addEventListener('contextmenu', function(e) {
    // 1. Проверяем, кликнули ли мы по файлу или по пустому месту
    const fileItem = e.target.closest('.file-item');
    const menu = document.getElementById('contextMenu');
    const menuName = document.getElementById('menuFileName');

    // Если кликнули по файлу — показываем полное меню
    if (fileItem) {
        const path = fileItem.dataset.path;
        const name = path.split('/').pop();
        
        // Подсвечиваем файл
        document.querySelectorAll('.file-item').forEach(el => el.style.background = "none");
        fileItem.style.background = "#303134";
        
        menuName.innerText = name;
        menuName.style.display = 'block';
        
        // Показываем кнопки удаления/переименования (они нужны для файла)
        toggleFileActions(true);
        
        // Сохраняем путь для действий
        window.currentContextPath = path;
    } else {
        // Если кликнули в пустом месте
        menuName.style.display = 'none';
        
        // Скрываем действия, которые привязаны к конкретному файлу (удалить, скачать и т.д.)
        toggleFileActions(false);
        
        // В этом случае контекстом будет текущая папка (из хлебных крошек или переменной)
        window.currentContextPath = null; 
    }

    // 2. Позиционируем меню
    e.preventDefault();
    menu.style.display = 'block';
    
    // Умное позиционирование, чтобы меню не уходило за край
    let x = e.clientX;
    let y = e.clientY;
    const menuWidth = 220;
    const menuHeight = menu.offsetHeight || 250;

    if (x + menuWidth > window.innerWidth) x -= menuWidth;
    if (y + menuHeight > window.innerHeight) y -= menuHeight;

    menu.style.left = x + 'px';
    menu.style.top = y + 'px';
});

// Вспомогательная функция для скрытия/показа пунктов меню
function toggleFileActions(show) {
    const fileOnlyItems = ['Копировать', 'Вырезать', 'Переименовать', 'Скачать', 'Удалить'];
    const buttons = document.querySelectorAll('#contextMenu div');
    
    buttons.forEach(btn => {
        const text = btn.innerText;
        if (fileOnlyItems.some(item => text.includes(item))) {
            btn.style.display = show ? 'flex' : 'none';
        }
    });
}


document.addEventListener('touchstart', e => {
    const it = e.target.closest('.file-item');
    if(it) longPressTimer = setTimeout(() => openCtxMenu(e), 600);
}, {passive: true});

document.addEventListener('touchend', () => clearTimeout(longPressTimer));
document.addEventListener('click', e => { if(!ctxMenu.contains(e.target)) ctxMenu.style.display='none'; });
document.addEventListener('change', e => { if(e.target.classList.contains('file-check')) updateBtn(); });

updateSys();
setInterval(updateSys, 10000);
function ctxAction(type) {
    console.log("Вызвано действие:", type, "для пути:", selectedPath);
    ctxMenu.style.display = 'none';
   
    if (!selectedPath && type !== 'paste') {
        console.error("Ошибка: selectedPath пуст!");
        return;
    }

    if (type === 'copy') copyFile(selectedPath);
    if (type === 'cut') cutFile(selectedPath);
    if (type === 'download') {
        const item = document.querySelector(`.file-item[data-path="${selectedPath}"]`);
        const isDir = item ? (item.querySelector('.file-icon').innerText.includes('📁')) : false;
        if (isDir) {
            const form = document.createElement('form');
            form.method = 'POST'; form.action = '/download_multi';
            const input = document.createElement('input');
            input.type = 'hidden'; input.name = 'paths'; input.value = JSON.stringify([selectedPath]);
            form.appendChild(input); document.body.appendChild(form);
            form.submit(); document.body.removeChild(form);
        } else {
            window.location.href = '/get/' + encodeURIComponent(selectedPath);
        }
    }

    if (type === 'delete') delItem(selectedPath);

    if (type === 'rename') runRename(selectedPath);

    // Копирование пути (исправлено, без внешних зависимостей)
    if (type === 'copyPath') {
        var t = document.createElement("textarea");
        t.value = "/" + selectedPath;
        document.body.appendChild(t);
        t.select();
        document.execCommand("copy");
        document.body.removeChild(t);
        showStatus("📍 Путь в буфере");
    }

    // ВСТАВКА (Исправлено определение пути папки)
    if (type === 'paste') {
        // Достаем путь из URL (из части /view/...)
        var currentPath = window.location.pathname.split('/view/')[1] || "";
        currentPath = decodeURIComponent(currentPath);
        
        // Убираем слэш в начале, если он есть (безопасно для Python)
        if (currentPath.indexOf('/') === 0) {
            currentPath = currentPath.substring(1);
        }

        showStatus("⏳ Вставка...");
        
        // Отправляем запрос
        fetch('/paste?to=' + encodeURIComponent(currentPath))
            .then(function(r) { return r.json(); })
            .then(function(d) {
                if (d.status === 'success') { 
                    showStatus("✅ Готово"); 
                    location.reload(); 
                } else {
                    alert("Ошибка: " + d.msg);
                }
            })
            .catch(function(err) {
                alert("Ошибка сети при вставке");
            });
    }
}




// Вспомогательная функция для переименования
async function runRename(oldPath) {
    const oldName = oldPath.split('/').pop();
    const newName = prompt("Введите новое имя:", oldName);
    if (newName && newName !== oldName) {
        const parent = oldPath.substring(0, oldPath.lastIndexOf('/'));
        const newPath = parent ? parent + '/' + newName : newName;
        const r = await fetch('/rename', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ old: oldPath, new: newPath })
        });
        if (r.ok) window.location.reload();
        else alert("Ошибка при переименовании");
    }
}
// Вспомогательная функция для уведомлений (если ее нет)
function showStatus(text) {
    const status = document.getElementById('apkStatus');
    if (status) {
        status.innerText = text;
        status.style.color = "#a8c7fa";
        // Убираем текст через 3 секунды
        setTimeout(() => { if(status.innerText === text) status.innerText = ""; }, 3000);
    }
}
async function createPrompt(isFolder) {
    const type = isFolder ? "папки" : "файла";
    const name = prompt(`Введите имя ${type}:`);
    
    if (!name) return;

    // Получаем текущую директорию из URL
    const currentDir = getCurrentPathFromURL();

    const response = await fetch('/create', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            name: name,
            current_dir: currentDir,
            is_folder: isFolder
        })
    });

    const result = await response.json();
    if (result.status === 'success') {
        location.reload(); // Обновляем список, чтобы увидеть созданное
    } else {
        alert("Ошибка: " + result.msg);
    }
}

// Не забудь функцию получения пути, которую мы обсуждали ранее
function getCurrentPathFromURL() {
    const path = window.location.pathname.split('/view/')[1] || "";
    return decodeURIComponent(path);
}

</script>

</body
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
    if not os.path.exists(full_path):
        return redirect('/view/') 
    items = []
    
    # 1. Сбор файлов
    if is_protected_path(full_path):
        output = run_rish(f"ls -1F '{full_path}' 2>/dev/null")
        if "ERROR:" in output or "status 1" in output:
            items = [{'name': '⚠️ Ошибка Shizuku/Доступа', 'is_dir': False}]
        else:
            lines = [l.strip() for l in output.splitlines() 
                     if l.strip() and "ls:" not in l and "linker" not in l and "WARNING" not in l]
            for l in lines:
                is_dir = l.endswith('/')
                items.append({'name': l.rstrip('/'), 'is_dir': is_dir})
    else:
        try:
            if os.path.exists(full_path):
                for entry in os.scandir(full_path):
                    items.append({'name': entry.name, 'is_dir': entry.is_dir()})
            else:
                items = [{'name': 'Папка не найдена', 'is_dir': False}]
        except Exception as e:
            items = [{'name': f'Ошибка: {str(e)}', 'is_dir': False}]

    items.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))

    # 2. Хлебные крошки
    breadcrumbs = []
    acc = ""
    if subpath:
        for part in subpath.split("/"):
            if part:
                acc = os.path.join(acc, part).strip("/")
                breadcrumbs.append({'name': part, 'url': acc})

    # 3. ВАЖНО: Убедись, что этот return находится ВНЕ всех условий if/else (в конце функции)
    return render_template_string(
        HTML_TEMPLATE, 
        items=items, 
        path=subpath, 
        breadcrumbs=breadcrumbs,
        parent_path=os.path.dirname(subpath),
        clipboard=CLIPBOARD["path"] is not None  # Чтобы кнопка "Вставить" работала
    )
@app.route('/multi_action', methods=['POST'])
@requires_auth
def multi_action():
    data = request.json
    paths = data.get('paths', [])
    action = data.get('action') # 'delete', 'copy', 'cut'
    
    if not paths:
        return jsonify({"status": "error", "msg": "Ничего не выбрано"}), 400

    if action == 'delete':
        for p in paths:
            full_path = os.path.join(BASE_DIR, p.strip("/"))
            run_rish(f"rm -rf '{full_path}'")
        return jsonify({"status": "success"})

    # Для копирования/вырезания сохраняем список в буфер
    if action in ['copy', 'cut']:
        global CLIPBOARD
        CLIPBOARD["paths"] = [os.path.join(BASE_DIR, p.strip("/")) for p in paths]
        CLIPBOARD["mode"] = action
        return jsonify({"status": "success", "count": len(paths)})

    return jsonify({"status": "error"}), 400
    
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
from flask import stream_with_context

@app.route('/get/<path:f_path>')
@requires_auth
def get_file(f_path):
    f_path = f_path.strip("/")
    full_target = os.path.join(BASE_DIR, f_path)

    if not os.path.exists(full_target) and not is_protected_path(full_target):
        return "Файл не найден", 404

    # Если это папка, вызываем download_multi и СРАЗУ передаем ей путь
    if os.path.isdir(full_target):
        return download_multi(manual_paths=[f_path]) 

    # Логика для Android/data
    if is_protected_path(full_target):
        def generate():
            cmd = f'rish -c "cat \'{full_target}\'"'
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            try:
                while True:
                    chunk = proc.stdout.read(128 * 1024)
                    if not chunk: break
                    yield chunk
            finally:
                proc.terminate()
                proc.wait()

        return Response(
            stream_with_context(generate()),
            mimetype='application/octet-stream',
            headers={"Content-Disposition": f"attachment; filename={os.path.basename(full_target)}"}
        )

    return send_file(full_target, as_attachment=True)


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
        
class ZipStreamWriter:
    def __init__(self):
        self.buffer = b""
    def write(self, data):
        if not data:
            return 0
        self.buffer += data
        return len(data)  # КРИТИЧНО: возвращаем количество байт
    def get_and_clear(self):
        data = self.buffer
        self.buffer = b""
        return data
    def flush(self):
        pass

@app.route('/download_multi', methods=['POST'])
@requires_auth
def download_multi(manual_paths=None):
    # 1. Получаем пути
    if manual_paths:
        paths = manual_paths
    else:
        try:
            paths = json.loads(request.form.get('paths', '[]'))
        except:
            return "Invalid paths", 400

    if not paths:
        return "No paths selected", 400

    # 2. Имя архива
    if len(paths) == 1:
        archive_name = os.path.basename(paths[0].rstrip('/')) + ".zip"
    else:
        archive_name = f"archive_{int(time.time())}.zip"

    def generate():
        stream = ZipStreamWriter()
        # Используем ZIP_STORED (без сжатия) для стабильности в Termux
        with zipfile.ZipFile(stream, mode='w', compression=zipfile.ZIP_STORED) as zf:
            for p in paths:
                f_full = os.path.join(BASE_DIR, p).rstrip('/')
                if not os.path.exists(f_full) and not is_protected_path(f_full):
                    continue

                # Рекурсивно собираем файлы
                if os.path.isdir(f_full):
                    for root, dirs, files in os.walk(f_full):
                        for file in files:
                            full_path = os.path.join(root, file)
                            # КЛЮЧЕВОЙ МОМЕНТ: Сохранение структуры
                            # arcname должен быть путем относительно родителя выбранной папки
                            arcname = os.path.relpath(full_path, os.path.dirname(f_full))
                            
                            yield from add_to_zip(zf, stream, full_path, arcname)
                else:
                    # Если это одиночный файл
                    yield from add_to_zip(zf, stream, f_full, os.path.basename(f_full))
        
        # Финальный сброс данных архива
        yield stream.get_and_clear()

    # Вспомогательная функция для записи байтов (внутри generate)
    def add_to_zip(zf, stream, full_path, arcname):
        zinfo = zipfile.ZipInfo(arcname, date_time=time.localtime(time.time())[:6])
        try:
            if is_protected_path(full_path):
                # Чтение через rish (Android/data)
                cmd = f'rish -c "cat \'{full_path}\' 2>/dev/null"'
                proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                with zf.open(zinfo, mode='w') as dest:
                    while True:
                        chunk = proc.stdout.read(128 * 1024)
                        if not chunk: break
                        dest.write(chunk)
                        yield stream.get_and_clear()
                proc.wait()
            else:
                # Обычное чтение (SD-карта)
                with open(full_path, 'rb') as f:
                    with zf.open(zinfo, mode='w') as dest:
                        while True:
                            chunk = f.read(128 * 1024)
                            if not chunk: break
                            dest.write(chunk)
                            yield stream.get_and_clear()
        except Exception as e:
            print(f"Ошибка архивации {full_path}: {e}")

    return Response(
        stream_with_context(generate()),
        mimetype='application/zip',
        headers={"Content-Disposition": f"attachment; filename={archive_name}"}
    )

@app.route('/delete/<path:f_path>')
@requires_auth
def delete_item(f_path):
    # Убеждаемся, что путь абсолютный от корня системы
    target = os.path.join(BASE_DIR, f_path.strip("/"))
    
    # Отладочный принт в консоль Termux - посмотри, что там напишет!
    print(f"DEBUG: Попытка удалить -> {target}")

    # Выполняем через rish с полными правами
    # Добавляем -f чтобы rm не задавал вопросов
    cmd = f'rish -c "rm -rf \'{target}\'"'
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    print(f"DEBUG: Ответ rish: {res.stdout} {res.stderr}")
    
    # Проверяем, исчез ли файл на самом деле
    if not os.path.exists(target):
        return "OK", 200
    else:
        return f"Ошибка: файл все еще на месте. Log: {res.stderr}", 500



@app.route('/copy/<path:f_path>')
@requires_auth
def copy_item(f_path):
    global CLIPBOARD
    print(f"--- СЕРВЕР ПОЛУЧИЛ СИГНАЛ КОПИРОВАНИЯ: {f_path} ---") # Проверка
    CLIPBOARD["path"] = os.path.join(BASE_DIR, f_path.strip("/"))
    return "OK", 200
@app.route('/rename', methods=['POST'])
@requires_auth # Не забудь добавить защиту!
def rename_item():
    data = request.json
    # Нам приходят относительные пути из JS, нужно превратить их в полные
    old_rel = data.get('old', '').strip("/")
    new_rel = data.get('new', '').strip("/")
    
    old_full = os.path.join(BASE_DIR, old_rel)
    new_full = os.path.join(BASE_DIR, new_rel)

    try:
        # Используем двойные кавычки для путей с пробелами
        cmd = f'rish -c "mv \\"{old_full}\\" \\"{new_full}\\""'
        subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, text=True)
        return jsonify({"ok": True, "msg": "Готово"})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500
@app.route('/cut/<path:f_path>')
@requires_auth
def cut_item(f_path):
    global CLIPBOARD
    CLIPBOARD["path"] = os.path.join(BASE_DIR, f_path.strip("/"))
    CLIPBOARD["mode"] = "cut"  # Устанавливаем режим вырезания
    print(f"✂️ Вырезано: {CLIPBOARD['path']}")
    return jsonify({"status": "success"})
@app.route('/create', methods=['POST'])
@requires_auth
def create_item():
    data = request.json
    # Находим полный путь: текущая папка + имя нового объекта
    target_path = os.path.join(BASE_DIR, data['current_dir'].strip("/"), data['name'])
    is_folder = data.get('is_folder', False)

    if os.path.exists(target_path):
        return jsonify({"status": "error", "msg": "Объект уже существует"}), 400

    # Создаем через rish (mkdir -p для папок, touch для файлов)
    cmd = f"mkdir -p '{target_path}'" if is_folder else f"touch '{target_path}'"
    res = run_rish(cmd)
    
    if "ERROR" in res:
        return jsonify({"status": "error", "msg": res}), 500
        
    return jsonify({"status": "success"})
    
@app.route('/paste')
@requires_auth
def paste_item():
    global CLIPBOARD
    # Получаем папку, в которую юзер хочет вставить файлы
    to_rel = request.args.get('to', '').strip("/")
    dst_dir = os.path.join(BASE_DIR, to_rel)

    # Собираем список исходных путей. 
    # Проверяем и новый массив "paths" (мультиселект) и старый "path" (одиночный)
    src_list = CLIPBOARD.get("paths") or []
    if not src_list and CLIPBOARD.get("path"):
        src_list = [CLIPBOARD["path"]]

    if not src_list:
        return jsonify({"status": "error", "msg": "Буфер обмена пуст"}), 400

    mode = CLIPBOARD.get("mode", "copy")
    # Выбираем команду: mv для вырезания, cp -pr для копирования
    action_cmd = "mv" if mode == "cut" else "cp -pr"
    
    errors = []
    success_count = 0

    for src in src_list:
        if not src or not os.path.exists(src):
            errors.append(f"Файл не найден: {os.path.basename(src)}")
            continue
            
        dst = os.path.join(dst_dir, os.path.basename(src))
        
        # Выполняем через rish
        cmd = f'rish -c "{action_cmd} \'{src}\' \'{dst}\'"'
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if res.returncode == 0:
            success_count += 1
        else:
            errors.append(f"Ошибка {os.path.basename(src)}: {res.stderr}")

    # Если был режим "вырезать", очищаем буфер после успешного завершения
    if mode == "cut":
        CLIPBOARD["paths"] = None
        CLIPBOARD["path"] = None

    if errors and success_count == 0:
        return jsonify({"status": "error", "msg": "Ничего не вставлено", "details": errors}), 500
    
    return jsonify({
        "status": "success", 
        "msg": f"Вставлено объектов: {success_count}",
        "errors": errors if errors else None
    })




if __name__ == "__main__":
    check_env()
    ip = get_ip()
    port = CONF.get("port", 5000)
    print(f"\n🚀 SERVER ACTIVE: http://{ip}:{port}\n")
    qr = qrcode.QRCode(box_size=1, border=2)
    qr.add_data(f"http://{ip}:{port}")
    qr.print_ascii()
    app.run(host='0.0.0.0', port=port, debug=False)
