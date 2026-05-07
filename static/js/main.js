let currentBook = null;
let currentSpineIndex = 0;
let spineList = [];
let isFetching = false;
let historyData = {};
let currentBookInfo = null;
let currentTocItems = [];
let loadSessionId = 0;
let isRestoringPosition = false;

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

    // 侧边栏靠近左侧自动唤出，离开后自动隐藏
    let sidebarHideTimer = null;

    function showSidebar() {
        clearTimeout(sidebarHideTimer);
        $('#sidebar').addClass('open');
    }

    function scheduleSidebarHide() {
        clearTimeout(sidebarHideTimer);
        sidebarHideTimer = setTimeout(() => {
            if (!$('#sidebar:hover').length && !$('#left-edge:hover').length) {
                $('#sidebar').removeClass('open');
            }
        }, 120);
    }

    $('#left-edge').on('mouseenter', showSidebar);
    $('#left-edge').on('mouseleave', scheduleSidebarHide);
    $('#sidebar').on('mouseenter', showSidebar);
    $('#sidebar').on('mouseleave', function() {
        $('#sidebar').removeClass('open');
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
        if (!isRestoringPosition && container[0].scrollHeight - container.scrollTop() - container.innerHeight() < 500) {
            if (!isFetching && currentSpineIndex + 1 < spineList.length) {
                loadNextChapter();
            }
        }
        
        if (currentBook) {
            if (!isRestoringPosition) {
                let progress = getCurrentProgress();
                updateHistoryActive(currentBook, progress.position, progress.spineIndex);
            }
            updateTOCActiveState(container.scrollTop());
        }
    });

    $('#toc-source').change(function() {
        renderTOC();
    });

    $(document).on('click', '.toc-item', function() {
        let index = $(this).data('index');
        if (index >= 0) {
            openBook(currentBook, index, 0, true);
        }
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

function getSelectedTOCItems() {
    if (!currentBookInfo) return [];
    let source = $('#toc-source').val();
    if (source === 'recommended') {
        source = currentBookInfo.toc_recommendation || 'original';
    }
    if (source === 'generated') {
        return currentBookInfo.generated_toc || [];
    }
    if (source === 'spine') {
        return currentBookInfo.spine_toc || [];
    }
    return currentBookInfo.original_toc || currentBookInfo.toc || [];
}

function renderTOC() {
    $('#toc-list').empty();
    currentTocItems = getSelectedTOCItems().filter(item => item.spineIndex >= 0);

    if (!currentBookInfo) {
        $('#toc-source-hint').text('');
        return;
    }

    let source = $('#toc-source').val();
    let quality = currentBookInfo.toc_quality || {};
    let hint = source === 'recommended' ? quality.reason : '';
    $('#toc-source-hint').text(hint);

    if (!currentTocItems.length) {
        $('#toc-list').append('<li class="toc-empty">暂无可跳转目录</li>');
        return;
    }

    currentTocItems.forEach(item => {
        let level = Math.max(1, Math.min(parseInt(item.level || 1), 4));
        $('<li></li>')
            .addClass(`toc-item toc-level-${level}`)
            .attr('data-index', item.spineIndex)
            .text(item.title)
            .appendTo('#toc-list');
    });

    updateTOCActiveState($('#content-container').scrollTop());
}

// Full save helper
function saveHistoryMap(map) {
    $.ajax({
        url: '/api/settings', // Wait! Currently settings and history have separate endpoints in the logic, but /api/history POST saves only the particular book currently. I need to make a unified call, or I'll just change the history endpoint to accept full map.
        // I will change the backend endpoint slightly, or I can update historyData in JS and send POST manually.
    });
}

let saveHistoryTimeout = null;
function getChapterTop(chapter) {
    return chapter[0].offsetTop - $('#reader-content')[0].offsetTop;
}

function getCurrentProgress() {
    let scrollTop = $('#content-container').scrollTop();
    let activeChapter = null;

    $('.chapter-container').each(function() {
        let chapter = $(this);
        if (getChapterTop(chapter) <= scrollTop + 100) {
            activeChapter = chapter;
        }
    });

    if (!activeChapter) {
        activeChapter = $('.chapter-container').first();
    }

    if (!activeChapter.length) {
        return { spineIndex: currentSpineIndex, position: scrollTop };
    }

    let spineIndex = activeChapter.data('spine-index');
    let position = Math.max(0, scrollTop - getChapterTop(activeChapter));
    return { spineIndex: spineIndex, position: position };
}

function saveHistoryNow(book, position) {
    $.ajax({
        url: '/api/history',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ book: book, position: position })
    });
}

function updateHistoryActive(book, position, spineIndex, immediate = false) {
    if (!historyData[book]) historyData[book] = {};
    historyData[book].position = position;
    historyData[book].spineIndex = spineIndex;
    historyData[book].timestamp = Date.now();

    clearTimeout(saveHistoryTimeout);
    if (immediate) {
        saveHistoryNow(book, historyData[book]);
        return;
    }

    saveHistoryTimeout = setTimeout(() => {
        saveHistoryNow(book, historyData[book]);
    }, 1000);
}

function updateTOCActiveState(scrollTop) {
    let currentIdx = currentSpineIndex;
    $('.chapter-container').each(function() {
        let chapter = $(this);
        if (getChapterTop(chapter) <= scrollTop + 100) {
            currentIdx = chapter.data('spine-index');
        }
    });
    $('.toc-item').removeClass('current-toc');
    let activeItem = $('.toc-item').filter(function() {
        return $(this).data('index') <= currentIdx;
    }).last();
    if (activeItem.length) {
        activeItem.addClass('current-toc');
    }
}

function openBook(filename, startSpine = 0, startPos = 0, saveImmediately = false) {
    let isSameBook = currentBook === filename;
    let sessionId = ++loadSessionId;
    isFetching = false;
    isRestoringPosition = true;
    currentBook = filename;
    currentBookInfo = null;
    currentTocItems = [];
    $('#current-book-name').text(filename);
    $('#reader-content').empty();
    $('#toc-list').empty();
    $('#toc-source-hint').text('');
    $('#content-container').scrollTop(0);
    currentSpineIndex = Math.max(0, startSpine - 1);

    // Update timestamp when opened
    if (!historyData[filename]) historyData[filename] = {};
    historyData[filename].timestamp = Date.now();
    renderHistory();

    $.get(`/api/book/${filename}`, function(info) {
        if (sessionId !== loadSessionId) return;
        currentBookInfo = info;
        spineList = info.spine;
        if (!isSameBook) {
            $('#toc-source').val('recommended');
        }
        renderTOC();
        startSpine = Math.max(0, Math.min(parseInt(startSpine) || 0, spineList.length - 1));
        startPos = Math.max(0, parseFloat(startPos) || 0);
        currentSpineIndex = Math.max(0, startSpine - 1);
        loadInitialChapters(startSpine, startPos, sessionId, saveImmediately);
    });
}

function finishPositionRestore(sessionId, saveImmediately, startSpine, startPos) {
    if (sessionId !== loadSessionId) return;

    let targetChapter = $(`.chapter-container[data-spine-index="${startSpine}"]`).first();
    if (targetChapter.length) {
        $('#content-container').scrollTop(getChapterTop(targetChapter) + startPos);
    }

    updateTOCActiveState($('#content-container').scrollTop());
    isRestoringPosition = false;

    if (saveImmediately) {
        updateHistoryActive(currentBook, startPos, startSpine, true);
    }

    if ($('#content-container')[0].scrollHeight <= $('#content-container').innerHeight() + 200) {
        if (currentSpineIndex + 1 < spineList.length) {
            loadNextChapter(sessionId);
        }
    }
}

function loadInitialChapters(startSpine, startPos, sessionId, saveImmediately) {
    let firstIndex = Math.max(0, startSpine - 1);
    loadChapterRange(firstIndex, startSpine, sessionId, function() {
        finishPositionRestore(sessionId, saveImmediately, startSpine, startPos);
    });
}

function loadChapterRange(index, endIndex, sessionId, done) {
    if (sessionId !== loadSessionId) return;
    if (index > endIndex) {
        done();
        return;
    }

    loadChapter(index, sessionId, function() {
        loadChapterRange(index + 1, endIndex, sessionId, done);
    });
}

function loadChapter(index, sessionId = loadSessionId, done = null) {
    if (sessionId !== loadSessionId || index >= spineList.length || index < 0 || isFetching) return;
    isFetching = true;

    let path = spineList[index];
    $.get(`/api/book/${currentBook}/file/${path}`)
    .done(function(content) {
        if (sessionId !== loadSessionId) return;

        let div = $(`<div class="chapter-container" data-spine-index="${index}"></div>`).html(content);
        $('#reader-content').append(div);
        currentSpineIndex = Math.max(currentSpineIndex, index);
        updateTOCActiveState($('#content-container').scrollTop());
        isFetching = false;

        if (done) {
            done();
            return;
        }

        if ($('#content-container')[0].scrollHeight <= $('#content-container').innerHeight() + 200) {
            if (index + 1 < spineList.length) {
                loadNextChapter(sessionId);
            }
        }
    })
    .fail(function() {
        if (sessionId === loadSessionId) {
            isFetching = false;
            if (done) done();
        }
    });
}

function loadNextChapter(sessionId = loadSessionId) {
    if (sessionId !== loadSessionId) return;
    loadChapter(currentSpineIndex + 1, sessionId);
}
