from flask import Flask, render_template, request, jsonify, send_file
import os
import posixpath
import json
import zipfile
import re
from urllib.parse import unquote
from bs4 import BeautifulSoup
import io

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BOOKS_DIR = os.path.join(BASE_DIR, 'books')
HISTORY_FILE = os.path.join(BASE_DIR, 'history.json')
SETTINGS_FILE = os.path.join(BASE_DIR, 'reader_settings.json')

os.makedirs(BOOKS_DIR, exist_ok=True)

def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return default
    return default

def save_json(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

AUXILIARY_TOC_KEYWORDS = (
    'cover', 'titlepage', 'toc', 'contents', 'caution', 'colophon', 'bookwalker',
    'copyright', 'fmatter', 'bmatter', 'backcover', 'author', 'summary', 'message',
    'illus', 'title.xhtml', '表紙', '封面', '目次', '目录', '奥付', '版权', '版權',
    'ご利用上の注意', 'プロフィール', '制作信息', '作者', '插画', '插圖',
    '彩页', '彩頁', '简介', '簡介'
)

CHAPTER_TITLE_PATTERN = re.compile(
    r'^(?:序章(?:$|[\s　:：].*)|終章(?:$|[\s　:：].*)|终章(?:$|[\s　:：].*)|'
    r'尾声(?:$|[\s　:：].*)|尾聲(?:$|[\s　:：].*)|后\s*记.*|後\s*記.*|あとがき.*|'
    r'译者\s*后记.*|譯者\s*後記.*|補遺.*|补遗.*|'
    r'第[一二三四五六七八九十〇零百千0-9０-９]+[章节話话幕部卷].*|'
    r'[一二三四五六七八九十〇零百千]+章(?:$|[\s　:：].*)|▲\s*[0-9０-９]+|[0-9０-９]+)$'
)

TITLE_CLASS_PATTERN = re.compile(r'(title|chapter|section|heading|midashi|biaoti|pius|font-1em30|class_s2h\d*)', re.I)


def clean_text(value):
    return re.sub(r'\s+', ' ', value or '').strip()


def normalize_epub_path(base_path, href):
    href = unquote((href or '').split('#')[0]).replace('\\', '/')
    base_path = (base_path or '').replace('\\', '/')
    path = posixpath.normpath(posixpath.join(base_path, href)).replace('\\', '/')
    return '' if path == '.' else path


def make_toc_item(title, src, level, source, spine_index_map):
    title = clean_text(title) or '未知章节'
    return {
        'title': title,
        'src': src,
        'level': level,
        'source': source,
        'spineIndex': spine_index_map.get(src, -1)
    }


def is_auxiliary_toc_item(item):
    value = f"{item.get('title', '')} {item.get('src', '')}".lower()
    return any(keyword.lower() in value for keyword in AUXILIARY_TOC_KEYWORDS)


def parse_nav_toc(z, toc_path, spine_index_map):
    nav_soup = BeautifulSoup(z.read(toc_path), 'html.parser')

    def is_toc_nav(tag):
        nav_type = tag.get('epub:type') or tag.get('type') or ''
        return tag.name == 'nav' and 'toc' in nav_type.split()

    nav = nav_soup.find(is_toc_nav) or nav_soup.find('nav')
    if not nav:
        return []

    toc = []
    toc_dir = posixpath.dirname(toc_path)

    def walk_list(list_node, level):
        for li in list_node.find_all('li', recursive=False):
            label = li.find(['a', 'span'], recursive=False)
            if not label:
                label = li.find(['a', 'span'])
            href = label.get('href', '') if label and label.name == 'a' else ''
            title = clean_text(label.get_text(' ', strip=True)) if label else ''
            if title:
                toc.append(make_toc_item(title, normalize_epub_path(toc_dir, href), level, 'original', spine_index_map))
            for child_list in li.find_all(['ol', 'ul'], recursive=False):
                walk_list(child_list, level + 1)

    root_list = nav.find(['ol', 'ul'])
    if root_list:
        walk_list(root_list, 1)
    return toc


def parse_ncx_toc(z, toc_path, spine_index_map):
    ncx_soup = BeautifulSoup(z.read(toc_path), 'xml')
    navmap = ncx_soup.find('navMap')
    if not navmap:
        return []

    toc = []
    toc_dir = posixpath.dirname(toc_path)

    def walk_navpoint(navpoint, level):
        label = navpoint.find('navLabel')
        title = clean_text(label.get_text(' ', strip=True) if label else '')
        content = navpoint.find('content')
        src = normalize_epub_path(toc_dir, content.get('src', '') if content else '')
        toc.append(make_toc_item(title, src, level, 'original', spine_index_map))
        for child in navpoint.find_all('navPoint', recursive=False):
            walk_navpoint(child, level + 1)

    for navpoint in navmap.find_all('navPoint', recursive=False):
        walk_navpoint(navpoint, 1)
    return toc


def normalize_generated_title(title):
    title = clean_text(title)
    number_match = re.fullmatch(r'[0-9０-９]+', title)
    if number_match:
        number = title.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
        return f'第 {number} 节'
    marker_match = re.fullmatch(r'▲\s*([0-9０-９]+)', title)
    if marker_match:
        number = marker_match.group(1).translate(str.maketrans('０１２３４５６７８９', '0123456789'))
        return f'▲{number}'
    return title


def extract_spine_title(z, filepath):
    try:
        soup = BeautifulSoup(z.read(filepath), 'html.parser')
    except KeyError:
        return '', 'missing', 0

    body = soup.find('body') or soup
    body_text = clean_text(body.get_text(' ', strip=True))

    for tag in body.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        title = clean_text(tag.get_text(' ', strip=True))
        if 1 <= len(title) <= 90:
            return normalize_generated_title(title), 'heading', len(body_text)

    for tag in body.find_all(True):
        class_text = ' '.join(tag.get('class', []))
        title = clean_text(tag.get_text(' ', strip=True))
        if TITLE_CLASS_PATTERN.search(class_text) and 1 <= len(title) <= 90 and CHAPTER_TITLE_PATTERN.search(title):
            return normalize_generated_title(title), 'title_class', len(body_text)

    meaningful_nodes = 0
    for tag in body.find_all(['p', 'div', 'span']):
        title = clean_text(tag.get_text(' ', strip=True))
        if not title:
            continue
        meaningful_nodes += 1
        if meaningful_nodes > 12:
            break
        if 1 <= len(title) <= 90 and CHAPTER_TITLE_PATTERN.search(title):
            return normalize_generated_title(title), 'chapter_pattern', len(body_text)

    for tag in body.find_all(['p', 'div']):
        title = clean_text(tag.get_text(' ', strip=True))
        if 4 <= len(title) <= 90:
            return normalize_generated_title(title), 'fallback', len(body_text)

    basename = posixpath.splitext(posixpath.basename(filepath))[0]
    return basename, 'filename', len(body_text)


def build_spine_toc(z, spine, spine_index_map):
    all_items = []
    generated_items = []

    for index, filepath in enumerate(spine):
        title, title_kind, text_length = extract_spine_title(z, filepath)
        all_item = make_toc_item(title, filepath, 1, 'spine', spine_index_map)
        all_item['spineIndex'] = index
        all_item['kind'] = title_kind
        all_items.append(all_item)

        candidate = dict(all_item)
        candidate['source'] = 'generated'
        is_auxiliary = is_auxiliary_toc_item(candidate)
        is_content_title = title_kind in ('heading', 'title_class', 'chapter_pattern') and not is_auxiliary
        is_long_numeric_section = title_kind == 'chapter_pattern' and text_length > 500 and not is_auxiliary
        if is_content_title or is_long_numeric_section:
            generated_items.append(candidate)

    return generated_items, all_items


def choose_toc_recommendation(original_toc, generated_toc, spine):
    content_original = [item for item in original_toc if not is_auxiliary_toc_item(item)]
    if generated_toc and len(content_original) == 0:
        return 'generated', '原目录只包含封面、奥付或版权等非正文项目'
    if generated_toc and len(content_original) < 3 and len(generated_toc) > len(content_original):
        return 'generated', '原目录正文条目较少，使用 spine 生成的目录'
    if generated_toc and len(original_toc) < max(3, len(spine) * 0.3) and len(generated_toc) > len(original_toc):
        return 'generated', '原目录覆盖的正文文件较少，使用智能目录'
    return 'original', '原目录已经足够丰富'


def parse_epub_structure(epub_path):
    with zipfile.ZipFile(epub_path, 'r') as z:
        container = z.read('META-INF/container.xml')
        soup = BeautifulSoup(container, 'xml')
        rootfile_path = soup.find('rootfile')['full-path']
        base_path = posixpath.dirname(rootfile_path)

        opf_soup = BeautifulSoup(z.read(rootfile_path), 'xml')
        manifest = {}
        for item in opf_soup.find_all('item'):
            manifest[item['id']] = {
                'href': normalize_epub_path(base_path, item.get('href', '')),
                'media_type': item.get('media-type', ''),
                'properties': item.get('properties', '')
            }

        spine = []
        spine_tag = opf_soup.find('spine')
        for itemref in spine_tag.find_all('itemref') if spine_tag else []:
            item = manifest.get(itemref.get('idref'))
            if item:
                spine.append(item['href'])

        spine_index_map = {path: index for index, path in enumerate(spine)}
        toc_path = None
        toc_parser = None

        for item in manifest.values():
            if 'nav' in item['properties'].split():
                toc_path = item['href']
                toc_parser = parse_nav_toc
                break

        if not toc_path and spine_tag and spine_tag.get('toc') in manifest:
            toc_path = manifest[spine_tag.get('toc')]['href']
            toc_parser = parse_ncx_toc

        if not toc_path:
            for item in manifest.values():
                if item['media_type'] == 'application/x-dtbncx+xml':
                    toc_path = item['href']
                    toc_parser = parse_ncx_toc
                    break

        original_toc = toc_parser(z, toc_path, spine_index_map) if toc_path and toc_parser else []
        generated_toc, spine_toc = build_spine_toc(z, spine, spine_index_map)
        recommendation, reason = choose_toc_recommendation(original_toc, generated_toc, spine)
        recommended_toc = generated_toc if recommendation == 'generated' else original_toc

        return {
            'spine': spine,
            'toc': original_toc,
            'original_toc': original_toc,
            'generated_toc': generated_toc,
            'spine_toc': spine_toc,
            'recommended_toc': recommended_toc,
            'toc_recommendation': recommendation,
            'toc_quality': {
                'source': 'none' if not toc_path else ('nav' if toc_parser == parse_nav_toc else 'ncx'),
                'original_count': len(original_toc),
                'original_content_count': len([item for item in original_toc if not is_auxiliary_toc_item(item)]),
                'generated_count': len(generated_toc),
                'spine_count': len(spine),
                'has_nested': any(item.get('level', 1) > 1 for item in original_toc),
                'reason': reason
            },
            'base_path': base_path
        }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/books')
def list_books():
    books = [f for f in os.listdir(BOOKS_DIR) if f.endswith('.epub')]
    return jsonify(books)

@app.route('/api/book/<filename>')
def get_book_info(filename):
    epub_path = os.path.join(BOOKS_DIR, filename)
    if not os.path.exists(epub_path):
        return jsonify({"error": "Book not found"}), 404
    info = parse_epub_structure(epub_path)
    return jsonify(info)

@app.route('/api/book/<filename>/file/<path:filepath>')
def get_book_file(filename, filepath):
    epub_path = os.path.join(BOOKS_DIR, filename)
    with zipfile.ZipFile(epub_path, 'r') as z:
        try:
            content = z.read(filepath)
            
            if filepath.endswith('.xhtml') or filepath.endswith('.html'):
                soup = BeautifulSoup(content, 'html.parser')
                
                # Replace image src
                for img in soup.find_all(['img', 'image']):
                    src = img.get('src') or img.get('xlink:href')
                    if src:
                        abs_src = os.path.normpath(os.path.join(os.path.dirname(filepath), src)).replace('\\', '/')
                        if img.name == 'img':
                            img['src'] = f"/api/book/{filename}/file/{abs_src}"
                        else:
                            img['xlink:href'] = f"/api/book/{filename}/file/{abs_src}"
                            
                for css in soup.find_all('link', rel='stylesheet'):
                    href = css.get('href')
                    if href:
                        abs_href = os.path.normpath(os.path.join(os.path.dirname(filepath), href)).replace('\\', '/')
                        css['href'] = f"/api/book/{filename}/file/{abs_href}"
                        
                content = str(soup).encode('utf-8')
                return content, 200, {'Content-Type': 'text/html; charset=utf-8'}
                
            mime_type = 'application/octet-stream'
            if filepath.endswith('.css'): mime_type = 'text/css'
            elif filepath.endswith('.jpg') or filepath.endswith('.jpeg'): mime_type = 'image/jpeg'
            elif filepath.endswith('.png'): mime_type = 'image/png'
            elif filepath.endswith('.gif'): mime_type = 'image/gif'
            elif filepath.endswith('.svg'): mime_type = 'image/svg+xml'
            
            return send_file(io.BytesIO(content), mimetype=mime_type)
        except KeyError:
            return "File not found in epub", 404

@app.route('/api/history', methods=['GET', 'POST'])
def handle_history():
    if request.method == 'GET':
        return jsonify(load_json(HISTORY_FILE, {}))
    elif request.method == 'POST':
        data = request.json
        history = load_json(HISTORY_FILE, {})
        history[data['book']] = data['position']
        save_json(HISTORY_FILE, history)
        return jsonify({"status": "success"})

@app.route('/api/settings', methods=['GET', 'POST'])
def handle_settings():
    if request.method == 'GET':
        return jsonify(load_json(SETTINGS_FILE, {"theme": "light", "show_jp": True, "font_size": 18}))
    elif request.method == 'POST':
        data = request.json
        save_json(SETTINGS_FILE, data)
        return jsonify({"status": "success"})

@app.route('/api/upload', methods=['POST'])
def upload_book():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    if file and file.filename.endswith('.epub'):
        filepath = os.path.join(BOOKS_DIR, file.filename)
        file.save(filepath)
        return jsonify({"status": "success", "filename": file.filename})
    return jsonify({"error": "Invalid file format"}), 400

if __name__ == '__main__':
    app.run(debug=True, port=5000)
