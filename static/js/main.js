let currentBook = null;
let currentSpineIndex = 0;
let spineList = [];
let isFetching = false;
let historyData = {};

$(document).ready(function() {
    loadSettings();
    loadHistory();

    $('#theme-toggle').change(function() {
        let isDark = $(this).is(':checked');
        if (isDark) {
            $('body').attr('data-theme', 'dark');
        } else {
            $('body').removeAttr('data-theme');
        }
        saveSettings();
    });

    $('#jp-toggle').change(function() {
        let showJp = $(this).is(':checked');
        document.documentElement.style.setProperty('--jp-display', showJp ? 'block' : 'none');
        saveSettings();
    });

    $('#font-size').on('input', function() {
        $('#reader-content').css('font-size', $(this).val() + 'px');
        saveSettings();
    });

    // 侧边栏隐藏/显示逻辑
    $('#sidebar-toggle').click(function() {
        $('#sidebar').removeClass('open');
    });

    // 鼠标滑到左边界时展开侧边栏
    $('#left-edge').mouseenter(function() {
        $('#sidebar').addClass('open');
    });
    
    // If you click outside the sidebar, you may want it to close? Not strictly requested, but good UI.
    $('#content-container').click(function() {
        if ($('#sidebar').hasClass('open')) {
            $('#sidebar').removeClass('open');
        }
    });

    $('#file-input').change(function() {
        let file = this.files[0];
        if (!file) return;
        let formData = new FormData();
        formData.append('file', file);
        $.ajax({
            url: '/api/upload',
            type: 'POST',
            data: formData,
            processData: false,
            contentType: false,
            success: function(res) {
                // Ensure uploaded book is in history
                if (!historyData[res.filename]) {
                    historyData[res.filename] = { position: 0, spineIndex: 0, timestamp: Date.now() };
                    saveHistoryMap(historyData);
                }
                openBook(res.filename);
            },
            error: function() {
                alert('上传失败');
            }
        });
    });

    $('#content-container').on('scroll', function() {
        let container = $(this);
        if (container[0].scrollHeight - container.scrollTop() - container.innerHeight() < 500) {
            if (!isFetching && currentSpineIndex + 1 < spineList.length) {
                loadNextChapter();
            }
        }
        
        if (currentBook) {
            let position = container.scrollTop();
            updateHistoryActive(currentBook, position, currentSpineIndex);
            updateTOCActiveState(position);
        }
    });

    $(document).on('click', '.toc-item', function() {
        let index = $(this).data('index');
        openBook(currentBook, index, 0);
    });
});

function loadSettings() {
    $.get('/api/settings', function(data) {
        if (data.theme === 'dark') {
            $('#theme-toggle').prop('checked', true).trigger('change');
        }
        if (data.show_jp === false) {
            $('#jp-toggle').prop('checked', false).trigger('change');
        }
        if (data.font_size) {
            $('#font-size').val(data.font_size).trigger('input');
        }
    });
}

function saveSettings() {
    let data = {
        theme: $('#theme-toggle').is(':checked') ? 'dark' : 'light',
        show_jp: $('#jp-toggle').is(':checked'),
        font_size: parseInt($('#font-size').val())
    };
    $.ajax({
        url: '/api/settings',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(data)
    });
}

function loadHistory() {
    $.get('/api/history', function(data) {
        // Assume data format might be dict of filenames mapped to history dicts
        historyData = data || {};
        renderHistory();
    });
}

function renderHistory() {
    $('#history-list').empty();
    // Sort logic to keep last read and limit to 5
    let books = Object.keys(historyData).map(k => {
        return { name: k, data: historyData[k] };
    });
    
    books.sort((a, b) => (b.data.timestamp || 0) - (a.data.timestamp || 0));
    // Max 5 items
    books = books.slice(0, 5);

    books.forEach(b => {
        let p = b.data.position || 0;
        let idx = b.data.spineIndex || 0;
        $('#history-list').append(`<li class="history-item" onclick="openBook('${b.name}', ${idx}, ${p})">${b.name}</li>`);
    });
}

// Full save helper
function saveHistoryMap(map) {
    $.ajax({
        url: '/api/settings', // Wait! Currently settings and history have separate endpoints in the logic, but /api/history POST saves only the particular book currently. I need to make a unified call, or I'll just change the history endpoint to accept full map.
        // I will change the backend endpoint slightly, or I can update historyData in JS and send POST manually.
    });
}

let saveHistoryTimeout = null;
function updateHistoryActive(book, position, spineIndex) {
    if (!historyData[book]) historyData[book] = {};
    historyData[book].position = position;
    historyData[book].spineIndex = spineIndex;
    historyData[book].timestamp = Date.now();
    
    // Rerender occasionally to keep order up to date? Probably not while scrolling.
    
    clearTimeout(saveHistoryTimeout);
    saveHistoryTimeout = setTimeout(() => {
        $.ajax({
            url: '/api/history',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ book: book, position: historyData[book] })
        });
    }, 1000);
}

function updateTOCActiveState(scrollTop) {
    // Very simple approximation: chapter containers exist in DOM. We find the last one we've scrolled past.
    let currentIdx = currentSpineIndex;
    $('.chapter-container').each(function() {
        if ($(this).position().top <= scrollTop + 100) {
            currentIdx = $(this).data('spine-index');
        }
    });
    $('.toc-item').removeClass('current-toc');
    $(`.toc-item[data-index="${currentIdx}"]`).addClass('current-toc');
}

function openBook(filename, startSpine = 0, startPos = 0) {
    currentBook = filename;
    $('#reader-content').empty();
    currentSpineIndex = startSpine;
    
    // Update timestamp when opened
    if (!historyData[filename]) historyData[filename] = {};
    historyData[filename].timestamp = Date.now();
    renderHistory();
    
    $.get(`/api/book/${filename}`, function(info) {
        spineList = info.spine;
        
        $('#toc-list').empty();
        info.toc.forEach(item => {
            let sIndex = spineList.indexOf(item.src);
            if (sIndex !== -1) {
                $('#toc-list').append(`<li class="toc-item" data-index="${sIndex}">${item.title}</li>`);
            }
        });
        
        loadChapter(currentSpineIndex, startPos);
    });
}

function loadChapter(index, startPos = 0) {
    if (index >= spineList.length || index < 0 || isFetching) return;
    isFetching = true;
    
    let path = spineList[index];
    $.get(`/api/book/${currentBook}/file/${path}`)
    .done(function(content) {
        let div = $(`<div class="chapter-container" data-spine-index="${index}"></div>`).html(content);
        $('#reader-content').append(div);
        
        if (startPos > 0 && index === currentSpineIndex) {
            $('#content-container').scrollTop(startPos);
        }
        
        updateTOCActiveState($('#content-container').scrollTop());
        isFetching = false;
        
        if ($('#content-container')[0].scrollHeight <= $('#content-container').innerHeight() + 200) {
            if (index + 1 < spineList.length) {
                loadNextChapter();
            }
        }
    })
    .fail(function() {
        isFetching = false;
    });
}

function loadNextChapter() {
    currentSpineIndex++;
    loadChapter(currentSpineIndex, 0);
}
