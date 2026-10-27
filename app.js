// --- CONFIGURATION ---
const API_BASE_URL = "";


const CONFIG = {
    DEFAULT_FPS: 30,
    MIN_SHOT_DURATION: 1.5,
    MIN_TRASH_DURATION: 0.5,
    TIMELINE_START_HOUR: 1
};

// --- DOM ELEMENTS ---
const landingScreen = document.getElementById('landing-screen');
const chatInterface = document.getElementById('chat-interface');
const chatBox = document.getElementById('chat-box');
const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const backBtn = document.getElementById('back-btn');
const newProjectBtn = document.getElementById('new-project-btn');
const sessionList = document.getElementById('session-list');
const uploadConfirmBtn = document.getElementById('upload-confirm-btn');
const videoInput = document.getElementById('video-input');
const uploadStatus = document.getElementById('upload-status');
const uploadArea = document.getElementById('upload-area');
const progressWrapper = document.getElementById('progress-wrapper');
const progressBar = document.getElementById('upload-progress-bar');
const progressPercent = document.getElementById('upload-percentage');
const uploadBox = document.querySelector('.upload-box');
const aiActions = document.querySelector('.ai-actions');
const uploadOptions = document.querySelector('.upload-options');
const inputWrapper = document.querySelector('.input-wrapper');
const navbar = document.querySelector('.navbar');
const modeTitle = document.getElementById('mode-title');
const navCredits = document.getElementById('nav-credits');
const mobileMenuBtn = document.getElementById('mobile-menu-btn');
const sidebar = document.querySelector('.chat-sidebar');

const modal = document.getElementById('instruction-modal');
const btnDownloadConfirm = document.getElementById('btn-download-confirm');
const btnModalClose = document.getElementById('btn-modal-close');
const chatUploadBtn = document.getElementById('chat-upload-btn');
const chatImageInput = document.getElementById('chat-image-input');
const imagePreviewContainer = document.getElementById('image-preview-container');
const imagePreview = document.getElementById('image-preview');
const removeImageBtn = document.getElementById('remove-image-btn');
const btnEdlCut = document.getElementById('btn-edl-cut');
const btnHighlights = document.getElementById('btn-highlights');

document.getElementById('current-year').textContent = new Date().getFullYear();

const authModal = document.getElementById('auth-modal');
const authEmail = document.getElementById('auth-email');
const authPass = document.getElementById('auth-password');
const btnLogin = document.getElementById('btn-login');
const btnRegister = document.getElementById('btn-register');
const authError = document.getElementById('auth-error');
const loginBtnNav = document.querySelector('.login-btn'); // Το κουμπί στο μενού πάνω δεξιά

// --- AUTH STATE ---
// Ελέγχουμε αν υπάρχει ήδη αποθηκευμένο token στον browser
let authToken = localStorage.getItem('access_token');
let userCredits = 0;
let userPlan = 'free';
let isPremiumUser = false;

// --- STATE ---
let currentMode = null;
let sessions = [];
let activeSessionId = null;
let isSidebarOpen = false; // Για το μενού κινητού
let wakeLock = null;       // Για να μην κλείνει η οθόνη
let currentImageBase64 = null;
let tempDownloadUrl = null;
let currentVideoMetadata = null;
let currentFileName = "";
let activeBotMessageElement = null;


// --- WAKE LOCK (Κρατάει την οθόνη ανοιχτή) ---
async function requestWakeLock() {
    try {
        if ('wakeLock' in navigator) {
            wakeLock = await navigator.wakeLock.request('screen');
            console.log('Wake Lock active');
        }
    } catch (err) { console.error(err); }
}

function releaseWakeLock() {
    if (wakeLock !== null) {
        wakeLock.release().then(() => { wakeLock = null; });
    }
}

// --- MOBILE MENU EVENTS ---
if (mobileMenuBtn) {
    mobileMenuBtn.addEventListener('click', () => {
        isSidebarOpen = !isSidebarOpen;
        // Απλά ανοίγουμε/κλείνουμε το μενού.
        // ΔΕΝ αλλάζουμε το εικονίδιο (μένει πάντα fa-bars).
        if (sidebar) sidebar.classList.toggle('open', isSidebarOpen);
    });
}


// ==========================================
// 📱 MOBILE SWIPE LOGIC & AUTO-CLOSE
// ==========================================

let touchStartX = 0;
let touchEndX = 0;

// 1. Καταγράφουμε πού ακούμπησε το δάχτυλο
document.addEventListener('touchstart', e => {
    touchStartX = e.changedTouches[0].screenX;
}, false);

// 2. Καταγράφουμε πού σηκώθηκε το δάχτυλο
document.addEventListener('touchend', e => {
    touchEndX = e.changedTouches[0].screenX;
    handleSwipe();
}, false);

function handleSwipe() {
    if (window.innerWidth > 768) return; // Μόνο σε κινητά

    const distance = touchEndX - touchStartX;
    const threshold = 60; // Πρέπει να σύρεις τουλάχιστον 60px για να πιάσει

    // SWIPE RIGHT (->) : ΑΝΟΙΓΜΑ
    // Ανοίγει μόνο αν σύρουμε προς τα δεξιά
    if (distance > threshold && !isSidebarOpen) {
        if (sidebar) sidebar.classList.add('open');
        isSidebarOpen = true;
    }

    // SWIPE LEFT (<-) : ΚΛΕΙΣΙΜΟ
    // Κλείνει αν σύρουμε προς τα αριστερά
    if (distance < -threshold && isSidebarOpen) {
        if (sidebar) sidebar.classList.remove('open');
        isSidebarOpen = false;
    }
}

// 3. ΚΛΕΙΣΙΜΟ ΟΤΑΝ ΠΑΤΑΣ ΣΤΟ CHAT
// Αν το μενού είναι ανοιχτό και πατήσεις στο κενό (στο chat), κλείνει.
const mainChatArea = document.querySelector('.chat-main');
if (mainChatArea) {
    mainChatArea.addEventListener('click', () => {
        if (isSidebarOpen && window.innerWidth <= 768) {
            if (sidebar) sidebar.classList.remove('open');
            isSidebarOpen = false;
        }
    });
}


// ==============================================================================
// 1. SESSION MANAGER & SIDEBAR LOGIC
// ==============================================================================

function createNewSession() {
    if (activeSessionId !== null) saveCurrentSessionState();

    const newId = Date.now();
    const type = currentMode;
    const count = sessions.filter(s => s.type === type).length + 1;
    const titleBase = type === 'video' ? 'Project' : 'Chat';

    const newSession = {
        id: newId,
        type: type,
        title: `${titleBase} ${count}`,
        history: [],
        videoName: null,
        edlUrl: null,
        isUploadComplete: false,
        isPinned: false
    };

    sessions.push(newSession);
    activeSessionId = newId;

    updateUIForSession(newSession);
    renderSidebar();
}

function switchSession(sessionId) {
   //Κλείσε το μενού αυτόματα (μόνο στα κινητά)
    if (window.innerWidth <= 768) {
        if(sidebar) sidebar.classList.remove('open');
        isSidebarOpen = false;
    }

    saveCurrentSessionState();
    const session = sessions.find(s => s.id === sessionId);
    if (!session) return;

    activeSessionId = sessionId;
    currentMode = session.type;

    updateUIForSession(session);

    chatBox.innerHTML = '';
    session.history.forEach(msg => {
        const div = document.createElement('div');
        // Προσθέτουμε τις σωστές κλάσεις για το CSS (user-message / bot-message)
        div.classList.add('message', msg.sender === 'user' ? 'user-message' : 'bot-message');
        
        const icon = msg.sender === 'user' ? '<i class="fas fa-user"></i>' : '<i class="fas fa-robot"></i>';

        let contentHtml = msg.imageUrl ? `<img src="${msg.imageUrl}" class="chat-image"><br>` : "";

        // --- Η ΔΙΟΡΘΩΣΗ ΓΙΑ ΤΟ FORMATTING ---
        if (msg.sender === 'bot') {
            // Το bot περνάει από το formatAIResponse (Bold, Headers, <br>)
            contentHtml += formatAIResponse(msg.text);
        } else {
            // Και ο χρήστης χρειάζεται τα Enter του να γίνονται <br>!
            contentHtml += msg.text.replace(/\n/g, '<br>');
        }

        // Δημιουργία του HTML
        div.innerHTML = `<div class="avatar">${icon}</div><div class="content">${contentHtml}</div>`;
        
        chatBox.appendChild(div);

        // Επαναφορά κουμπιών (αν υπάρχουν στο ιστορικό)
        // ΣΗΜΕΙΩΣΗ: Εδώ ελέγχουμε αν το μήνυμα είχε URL για download
        // Αν θες να θυμάται τα κουμπιά που έβγαλε το AI (π.χ. clips), 
        // ίσως χρειαστεί να αποθηκεύουμε και το 'downloadUrl' στο history object.
        if (msg.hasDownload && session.edlUrl) {
            appendDownloadButton(session.edlUrl, div.querySelector('.content'));
        }
    });

    // Scroll automatically στο τέλος
    chatBox.scrollTop = chatBox.scrollHeight;
    

    renderSidebar();
}

function updateUIForSession(session) {
    // 1. Κρύβουμε όλα τα κεντρικά στοιχεία για να έχουμε καθαρό καμβά
    document.getElementById('upload-area').classList.add('hidden');
    document.querySelector('.input-wrapper').classList.add('hidden');
    document.getElementById('colorist-area').classList.add('hidden');

    // 2. Ελέγχουμε τι mode είναι το επιλεγμένο session
    if (session.type === 'help') {
        // --- CHAT EXPERT ---
        modeTitle.innerText = "DaVinci Resolve Expert";
        newProjectBtn.innerHTML = '<i class="fas fa-plus"></i> New Chat';
        document.querySelector('.input-wrapper').classList.remove('hidden');
        chatUploadBtn.style.display = 'inline-block';
        if (session.history.length === 0) {
            chatBox.innerHTML = '';
            addMessage('bot', 
                "👋 **Hello! I'm your DaVinci Resolve Assistant.**\n\n" +
                "To help you better, tell me your experience level:\n" +
                "🟢 **I am a Beginner** (I need step-by-step instructions)\n" +
                "🔴 **I am an Expert** (Just give me the technical solution)"
            );
        }
        
    } else if (session.type === 'colorist') {
        // --- AI COLORIST ---
        modeTitle.innerText = "AI Colorist";
        newProjectBtn.innerHTML = '<i class="fas fa-plus"></i> New Grade';
        document.getElementById('colorist-area').classList.remove('hidden');
        chatUploadBtn.style.display = 'none';
        
        // Αν είναι εντελώς νέο project, καθάρισε τα παλιά ροδάκια/φωτογραφίες
        if (session.history.length === 0) {
            document.getElementById('colorist-upload-box').classList.remove('hidden');
            document.getElementById('colorist-workspace').classList.add('hidden');
            document.getElementById('colorist-results').innerHTML = '';
            coloristImageBase64 = null;
            document.getElementById('colorist-preview').src = "";
        }

        
    } else {
        // --- VIDEO UPLOAD (Media Intelligence) ---
        modeTitle.innerText = "Media Intelligence";
        newProjectBtn.innerHTML = '<i class="fas fa-plus"></i> New Project';
        chatUploadBtn.style.display = 'none';
        
        if (!session.isUploadComplete) {
            resetInterfaceForUpload();
        } else {
            document.querySelector('.input-wrapper').classList.remove('hidden');
        }
    }
}

function renderSidebar() {
    sessionList.innerHTML = '';
    let filteredSessions = sessions.filter(s => s.type === currentMode);

    filteredSessions.sort((a, b) => {
        if (a.isPinned && !b.isPinned) return -1;
        if (!a.isPinned && b.isPinned) return 1;
        return b.id - a.id;
    });

    filteredSessions.forEach(session => {
        const div = document.createElement('div');
        div.className = `history-item ${session.id === activeSessionId ? 'active' : ''}`;

        let iconHtml = '';
        if (session.isPinned) {
            iconHtml = '<i class="fas fa-thumbtack pinned-icon"></i>';
        } else {
            iconHtml = session.type === 'video'
                ? (session.videoName ? '<i class="fas fa-film"></i>' : '<i class="far fa-circle"></i>')
                : '<i class="fas fa-graduation-cap"></i>';
        }

        const title = session.videoName || session.title;
        const displayTitle = title.length > 15 ? title.substring(0, 15) + '...' : title;

        div.innerHTML = `
            <div class="item-content" style="flex-grow: 1; display: flex; align-items: center; gap: 8px; cursor: pointer;">
                ${iconHtml} <span>${displayTitle}</span>
            </div>
            <button class="menu-trigger"><i class="fas fa-ellipsis-v"></i></button>
            <div class="context-menu" id="menu-${session.id}">
                <button onclick="togglePinSession(${session.id})">
                    <i class="fas fa-thumbtack"></i> ${session.isPinned ? 'Unpin' : 'Pin'}
                </button>
                <button onclick="renameSession(${session.id})">
                    <i class="fas fa-pen"></i> Rename
                </button>
                <button class="delete-btn" onclick="deleteSession(${session.id})">
                    <i class="fas fa-trash"></i> Delete
                </button>
            </div>
        `;

        div.onclick = (e) => {
            // Αν πατήσαμε το κουμπάκι με τις τελείες ή το μενού, ΜΗΝ αλλάξεις session
            if (e.target.closest('.menu-trigger') || e.target.closest('.context-menu')) return;
            
            // Έλεγχος αν "κλειδώσαμε" το sidebar (π.χ. ανεβάζει βίντεο)
            if (document.getElementById('new-project-btn').disabled) return;

            switchSession(session.id);
        };

        const trigger = div.querySelector('.menu-trigger');
        const menu = div.querySelector('.context-menu');

        trigger.onclick = (e) => {
            e.stopPropagation();
            document.querySelectorAll('.context-menu').forEach(m => {
                if (m !== menu) m.classList.remove('show');
            });
            document.querySelectorAll('.history-item').forEach(i => i.classList.remove('menu-active'));
            menu.classList.toggle('show');
            div.classList.toggle('menu-active');
        };

        sessionList.appendChild(div);
    });
}

window.togglePinSession = function (sessionId) {
    const session = sessions.find(s => s.id === sessionId);
    if (session) {
        session.isPinned = !session.isPinned;
        renderSidebar();
    }
}

window.renameSession = async function (sessionId) {
    const session = sessions.find(s => s.id === sessionId);
    if (session) {
        // Κλείνουμε τα μενού
        document.querySelectorAll('.context-menu').forEach(m => m.classList.remove('show'));
        
        setTimeout(async () => {
            const currentTitle = session.videoName || session.title;
            const newTitle = prompt("Enter new name:", currentTitle);
            
            if (newTitle && newTitle.trim() !== "" && newTitle !== currentTitle) {
                // 1. Ενημέρωση στο UI (τοπικά)
                if (session.type === 'video') session.videoName = newTitle.trim();
                else session.title = newTitle.trim();
                renderSidebar();

                // 2. Ενημέρωση στο Backend (Railway) - ΜΟΝΟ αν έχει κανονικό ID από τη βάση
                if (sessionId < 1000000000000) {
                    try {
                        await fetch(`${API_BASE_URL}/projects/${sessionId}`, {
                            method: 'PUT',
                            headers: { 
                                'Content-Type': 'application/json',
                                'Authorization': `Bearer ${authToken}` 
                            },
                            body: JSON.stringify({ filename: newTitle.trim() })
                        });
                    } catch (e) {
                        console.error("Rename failed on server:", e);
                    }
                }
            }
        }, 100);
    }
}

window.deleteSession = async function (sessionId) {
    if (confirm("Are you sure you want to delete this?")) {
        // 1. Διαγραφή από το UI (τοπικά)
        sessions = sessions.filter(s => s.id !== sessionId);
        if (activeSessionId === sessionId) {
            const remaining = sessions.filter(s => s.type === currentMode);
            if (remaining.length > 0) switchSession(remaining[0].id);
            else createNewSession();
        } else {
            renderSidebar();
        }

        // 2. Διαγραφή από το Backend (Railway)
        if (sessionId < 1000000000000) {
            try {
                await fetch(`${API_BASE_URL}/projects/${sessionId}`, {
                    method: 'DELETE',
                    headers: { 'Authorization': `Bearer ${authToken}` }
                });
            } catch (e) {
                console.error("Delete failed on server:", e);
            }
        }
    }
}

document.addEventListener('click', (e) => {
    if (!e.target.closest('.menu-trigger') && !e.target.closest('.context-menu')) {
        document.querySelectorAll('.context-menu').forEach(m => m.classList.remove('show'));
        document.querySelectorAll('.history-item').forEach(i => i.classList.remove('menu-active'));
    }
});

function saveCurrentSessionState() { }

function toggleSidebarLock(isLocked) {
    newProjectBtn.disabled = isLocked;
    const items = document.querySelectorAll('.history-item');
    items.forEach(item => {
        if (isLocked) item.classList.add('disabled-link');
        else item.classList.remove('disabled-link');
    });
}

function resetInterfaceForUpload() {
    chatBox.innerHTML = '';
    uploadArea.classList.remove('hidden');
    document.getElementById('colorist-area').classList.add('hidden');
    uploadBox.classList.remove('hidden');
    aiActions.classList.remove('hidden');
    uploadOptions.classList.remove('hidden');
    inputWrapper.classList.add('hidden');
    uploadStatus.innerText = "";
    videoInput.value = "";
    uploadConfirmBtn.disabled = false;
    toggleSidebarLock(false);
    currentFileName = "";
    currentVideoMetadata = null;
}

// ==============================================================================
// 2. LOGIC (THE AI BRAIN)
// ==============================================================================

const PROMPTS = {
    EDL: `You are a Senior Film Editor with 20 years of experience.
    OBJECTIVE: Analyze the footage and separate "Cinematic Action" from "Technical Garbage".

    CRITICAL MOTION RULES (READ CAREFULLY):
    1. WHIP PAN (KEEP): Rapid horizontal camera movement to change subjects. This is a transition. DO NOT CUT.
    2. HANDHELD (KEEP): Camera shake where the subject remains framed (e.g., Bourne Identity style). This is "Energy". DO NOT CUT.
    3. GARBAGE (CUT): 
        - Accidental Floor/Ceiling shots.
        - Focus Hunting (pulsing blur where nothing is clear).
        - Rolling Shutter Jello (extreme geometric warping).
    
    SAFETY PROTOCOL:
    If you are unsure if motion is "Action" or "Shake", KEEP IT. It is better to include a bad shot than cut a good one.
 
    OUTPUT FORMAT (JSON ONLY):
    {
      "bad_segments": [
        {"start": "MM:SS", "end": "MM:SS", "reason": "floor shot"},
        {"start": "MM:SS", "end": "MM:SS", "reason": "focus hunting"}
      ]
    }
    Return ONLY VALID JSON string. No Markdown.`,
    HIGHLIGHTS: `Find the most engaging moments (Action, Emotion, Kills, Funny moments, Goals, ext).
    
    CRITICAL INSTRUCTION:
    Return ONLY a raw JSON object. 
    DO NOT write "Here are the clips". 
    DO NOT generate Markdown links like [Title](url).
    DO NOT add any text before or after the JSON.
    
    JSON FORMAT:
    {
    "viral_clips": [
        {
        "start": "MM:SS",
        "end": "MM:SS",
        "title": "Short Title",
        "reason": "Why is this viral?",
        "hashtags": "#Tag1 #Tag2"
        }
    ]
    }`
};

class Timecode {
    constructor(fps, startTcString = "00:00:00:00") {
        this.fps = fps;
        this.startFrames = this.parseTimeStr(startTcString);
    }

    secondsToSMPTE(secondsFromStart) {
        const totalFrames = Math.floor(this.startFrames + (secondsFromStart * this.fps));
        const frPerSec = Math.round(this.fps);
        const ff = totalFrames % frPerSec;
        const totalSeconds = Math.floor(totalFrames / frPerSec);
        const ss = totalSeconds % 60;
        const mm = Math.floor(totalSeconds / 60) % 60;
        const hh = Math.floor(totalSeconds / 3600);
        const pad = (n) => n.toString().padStart(2, '0');
        return `${pad(hh)}:${pad(mm)}:${pad(ss)}:${pad(ff)}`;
    }

    parseTimeStr(timeStr) {
        const parts = timeStr.replace(';', ':').split(':').map(Number);
        if (parts.length === 4) {
            return (parts[0] * 3600 * this.fps) + (parts[1] * 60 * this.fps) + (parts[2] * this.fps) + parts[3];
        }
        return 0;
    }
}

function generateRobustEDL(jsonResponse, metadata, filename) {
    try {
        let cleanJson = jsonResponse.replace(/```json/g, '').replace(/```/g, '').trim();
        const firstBrace = cleanJson.indexOf('{');
        const lastBrace = cleanJson.lastIndexOf('}');
        if (firstBrace !== -1 && lastBrace !== -1) {
            cleanJson = cleanJson.substring(firstBrace, lastBrace + 1);
        }

        const parsed = JSON.parse(cleanJson);
        const badSegments = parsed.bad_segments || [];

        const fps = metadata.fps || CONFIG.DEFAULT_FPS;
        const duration = metadata.duration;
        const startTc = metadata.start_tc || "00:00:00:00";

        const tcEngine = new Timecode(fps, startTc);
        const recEngine = new Timecode(fps, "01:00:00:00");

        let keepSegments = [];
        let cursor = 0.0;

        const parseRelative = (t) => {
            const p = t.split(':').map(Number);
            return (p[0] * 60) + p[1];
        };

        const sortedTrash = badSegments.map(seg => ({
            start: parseRelative(seg.start),
            end: parseRelative(seg.end)
        })).sort((a, b) => a.start - b.start);

        sortedTrash.forEach(bad => {
            let gap = bad.start - cursor;

            if (gap >= CONFIG.MIN_SHOT_DURATION) {
                keepSegments.push({ start: cursor, end: bad.start });
            }
            cursor = Math.max(cursor, bad.end);
        });

        if (cursor < duration - 0.5) keepSegments.push({ start: cursor, end: duration });

        if (keepSegments.length === 0 && badSegments.length === 0) {
            keepSegments.push({ start: 0, end: duration });
        }

        const reelName = "AX       ";

        let edlBody = `TITLE: AI_CUT_${filename}\nFCM: NON-DROP FRAME\n\n`;
        let recordCursorSec = 0;

        keepSegments.forEach((seg, index) => {
            let segDur = seg.end - seg.start;
            let srcIn = tcEngine.secondsToSMPTE(seg.start);
            let srcOut = tcEngine.secondsToSMPTE(seg.end);
            let recIn = recEngine.secondsToSMPTE(recordCursorSec);
            let recOut = recEngine.secondsToSMPTE(recordCursorSec + segDur);
            let eventNum = (index + 1).toString().padStart(3, '0');

            edlBody += `${eventNum}  ${reelName} V     C         ${srcIn} ${srcOut} ${recIn} ${recOut}\n`;
            edlBody += `* FROM CLIP NAME: ${filename}\n\n`;

            recordCursorSec += segDur;
        });
        return edlBody;
    } catch (e) {
        console.error("Logic Error:", e);
        return null;
    }
}

// ==============================================================================
// 3. CHAT LOGIC (UPDATED WITH CARDS SUPPORT)
// ==============================================================================

function typeWriter(element, text, speed = 1, callback = null) {
    let i = 0;
    element.innerHTML = "";
    element.classList.add('typing-cursor');

    // Απενεργοποίηση εφέ γραφομηχανής αν έχει HTML (κάρτες)
    if (text.includes('<div class="clips-grid">')) {
        element.innerHTML = text;
        element.classList.remove('typing-cursor');
        if (callback) callback();
        return;
    }

    function type() {
        if (i < text.length) {
            const isNearBottom = chatBox.scrollHeight - chatBox.scrollTop <= chatBox.clientHeight + 100;
            if (text.charAt(i) === '<') {
                let tagEnd = text.indexOf('>', i);
                if (tagEnd !== -1) { element.innerHTML += text.substring(i, tagEnd + 1); i = tagEnd + 1; }
                else { element.innerHTML += text.charAt(i); i++; }
            } else { element.innerHTML += text.charAt(i); i++; }

            if (isNearBottom) chatBox.scrollTop = chatBox.scrollHeight;
            setTimeout(type, speed);
        } else {
            element.classList.remove('typing-cursor');
            if (callback) callback();
        }
    }
    type();
}

function createThinkingMessage() {
    const div = document.createElement('div');
    div.classList.add('message', 'bot-message');
    div.innerHTML = `<div class="avatar thinking"><i class="fas fa-robot"></i></div><div class="content"><p></p></div>`;
    chatBox.appendChild(div);
    chatBox.scrollTop = chatBox.scrollHeight;
    return { container: div, avatar: div.querySelector('.avatar'), textElement: div.querySelector('p') };
}

// --- ΣΗΜΑΝΤΙΚΗ ΑΛΛΑΓΗ ΕΔΩ ΓΙΑ ΤΑ ΚΟΥΤΑΚΙΑ ---
function resolveThinkingMessage(messageObj, text, onComplete = null) {
    if (!messageObj) return;
    messageObj.avatar.classList.remove('thinking');

    // 1. Περνάμε το κείμενο από το φίλτρο Format (που φτιάχνει κάρτες και σβήνει JSON)
    let formattedText = formatAIResponse(text);

    // 2. Αν δεν έχει κάρτες, κάνουμε bolding και newlines
    if (!formattedText.includes('class="clips-grid"')) {
        formattedText = formattedText.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');
    }

    // 3. Εμφάνιση
    typeWriter(messageObj.textElement, formattedText, 1, onComplete);

    const session = sessions.find(s => s.id === activeSessionId);
    // Αποθηκεύουμε το ORIGINAL text στο ιστορικό, όχι το HTML, για να μην χαλάσει
    if (session) session.history.push({ sender: 'bot', text: text, hasDownload: false });
}

function appendDownloadButton(url, parentElement) {
    const btnContainer = document.createElement('div');
    btnContainer.style.display = 'flex';
    btnContainer.style.gap = '10px';
    btnContainer.style.marginTop = '10px';

    const btn = document.createElement('button');
    btn.innerHTML = '<i class="fas fa-download"></i> Download .EDL Timeline';
    btn.className = "download-btn";
    btn.onclick = () => { tempDownloadUrl = url; modal.classList.remove('hidden'); };

    btnContainer.appendChild(btn);
    parentElement.appendChild(btnContainer);
}

function createDownloadButton(content) {
    const blob = new Blob([content], { type: 'text/plain' });
    const url = window.URL.createObjectURL(blob);

    const session = sessions.find(s => s.id === activeSessionId);
    if (session) {
        session.edlUrl = url;
        if (session.history.length > 0) session.history[session.history.length - 1].hasDownload = true;
    }

    if (chatBox.lastElementChild) {
        appendDownloadButton(url, chatBox.lastElementChild.querySelector('.content'));
        chatBox.scrollTop = chatBox.scrollHeight;
    }
}

// ==============================================================================
// 4. EVENTS & UPLOAD
// ==============================================================================

newProjectBtn.addEventListener('click', createNewSession);
btnModalClose.addEventListener('click', () => modal.classList.add('hidden'));
btnDownloadConfirm.addEventListener('click', () => {
    if (tempDownloadUrl) {
        const a = document.createElement('a');
        a.href = tempDownloadUrl;
        a.download = `AI_RoughCut_${Date.now()}.edl`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        modal.classList.add('hidden');
    }
});

['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    uploadBox.addEventListener(eventName, e => { e.preventDefault(); e.stopPropagation(); }, false);
});
uploadBox.addEventListener('drop', handleDrop, false);
videoInput.addEventListener('change', (e) => { if (e.target.files.length > 0) processFileDetails(e.target.files[0]); });

function handleDrop(e) {
    if (e.dataTransfer.files.length > 0) {
        videoInput.files = e.dataTransfer.files;
        processFileDetails(e.dataTransfer.files[0]);
    }
}

function processFileDetails(file) {
    currentFileName = file.name;
}

document.getElementById('btn-import-media').addEventListener('click', () => setupMode('video'));
document.getElementById('btn-resolve-help').addEventListener('click', () => setupMode('help'));
backBtn.addEventListener('click', () => {
    landingScreen.classList.remove('hidden');
    chatInterface.classList.add('hidden');
    navbar.classList.remove('hidden');
});

function setupMode(mode) {
    currentMode = mode;
    landingScreen.classList.add('hidden');
    chatInterface.classList.remove('hidden');
    navbar.classList.add('hidden');

    if (sidebar && window.innerWidth <= 768) {
        sidebar.classList.remove('open'); // Κλείσε το μενού
        isSidebarOpen = false;            // Ενημέρωσε τη μεταβλητή
        if(mobileMenuBtn) mobileMenuBtn.innerHTML = '<i class="fas fa-bars"></i>'; // Γύρνα το εικονίδιο σε γραμμές
    }

    const existing = sessions.filter(s => s.type === mode);
    if (existing.length > 0) switchSession(existing[existing.length - 1].id);
    else createNewSession();
}

// ==========================================
// ✅ ΝΕΑ ΛΟΓΙΚΗ ΚΟΥΜΠΙΩΝ (CLEAN VERSION)
// ==========================================

// 1. ΚΟΥΜΠΙ UPLOAD (Custom Prompt)
uploadConfirmBtn.addEventListener('click', () => {
    const userText = document.getElementById('video-prompt-input').value.trim();
    performUpload(userText, null); // Στέλνουμε κείμενο, ΟΧΙ mode
});

// 2. ΚΟΥΜΠΙ "CREATE ROUGH CUT" (EDL)
btnEdlCut.addEventListener('click', () => {
    performUpload(null, 'rough_cut'); // Στέλνουμε mode, ΟΧΙ κείμενο
});

// 3. ΚΟΥΜΠΙ "VIRAL SHORTS" (Highlights)
btnHighlights.addEventListener('click', () => {
    performUpload(null, 'viral'); // Στέλνουμε mode, ΟΧΙ κείμενο
});

// ==========================================
// ✅ Η ΚΥΡΙΑ ΣΥΝΑΡΤΗΣΗ UPLOAD
// ==========================================
async function performUpload(promptText, modeName) {
    if (!authToken) {
        alert("Please sign up or log in first to get your 3 free credits!");
        authModal.classList.remove('hidden'); // Ανοίγει το παράθυρο για να γραφτεί
        return;
    }
    const files = videoInput.files;

    if (files.length === 0) return alert("Please select a video.");
    if (files.length > 1) return alert("Please select only ONE video.");



    if (userCredits <= 0) {
        alert("You have run out of credits! Please upgrade your plan.");
        pricingModal.classList.remove('hidden');
        return;
    }

    // --- ΕΛΕΓΧΟΣ ΟΡΙΟΥ ΜΕΓΕΘΟΥΣ ΒΙΝΤΕΟ (5GB / 20GB) ---
    const fileToUpload = files[0];
    const fileSizeGB = fileToUpload.size / (1024 * 1024 * 1024); // Μετατροπή Bytes σε GB
    
    let maxLimitGB = 5; // Προεπιλογή (Απλό πλάνο ή Free)
    
    // Ελέγχουμε το ΑΛΗΘΙΝΟ status του χρήστη από τη βάση δεδομένων
    if (userPlan === 'pro') { 
    maxLimitGB = 20; // ΜΟΝΟ το Pro παίρνει 20GB
    }

    if (fileSizeGB > maxLimitGB) {
        alert(`⚠️ File too large!\n\nYour current plan allows files up to ${maxLimitGB}GB.\nThis video is ${fileSizeGB.toFixed(1)}GB.\n\nPlease upgrade your plan or select a smaller video.`);
        return; // Σταματάει το upload
    }
    // ------------------------------------------------

    // Μηνύματα UI
    let userMsg = "Analyzing...";
    if (modeName === 'rough_cut') userMsg = "✂️ Auto-Cut: Removing Trash & Creating EDL...";
    if (modeName === 'viral') userMsg = "🔥 Analyzing for Viral Highlights...";
    if (promptText) userMsg = `Custom Analysis: "${promptText}"`;

    uploadConfirmBtn.disabled = true;
    toggleSidebarLock(true);
    addMessage('user', userMsg);

    uploadBox.classList.add('hidden');
    aiActions.classList.add('hidden');
    uploadOptions.classList.add('hidden');
    progressWrapper.classList.remove('hidden');
    progressBar.style.width = '0%';
    progressPercent.innerText = '0%';
    uploadStatus.innerText = "Initializing...";
    await requestWakeLock(); // Κρατάμε οθόνη ανοιχτή


    

    try {
        const urlRes = await fetch(`${API_BASE_URL}/generate-presigned-url`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                filename: fileToUpload.name,
                file_type: fileToUpload.type || 'application/octet-stream'
            })
        });

        if (!urlRes.ok) throw new Error("Could not get Cloudflare URL");
        const { upload_url, file_key } = await urlRes.json();

        // --- 2. ΣΤΕΛΝΟΥΜΕ ΤΟ ΒΙΝΤΕΟ ΣΤΟ CLOUDFLARE ---
        const xhr = new XMLHttpRequest();
        xhr.open('PUT', upload_url, true);
        xhr.setRequestHeader('Content-Type', fileToUpload.type || 'application/octet-stream');

        let fakeProgress = 0;
        const fakeInterval = setInterval(() => {
            if (fakeProgress < 30) {
                fakeProgress += Math.random() * 2;
                if (parseFloat(progressBar.style.width) < fakeProgress) {
                    progressBar.style.width = fakeProgress + '%';
                    progressPercent.innerText = Math.round(fakeProgress) + '%';
                }
            } else clearInterval(fakeInterval);
        }, 200);

        xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) {
                let percent = (e.loaded / e.total) * 100;
                if (percent > fakeProgress) {
                    clearInterval(fakeInterval);
                    progressBar.style.width = percent + '%';
                    progressPercent.innerText = Math.round(percent) + '%';
                }
                if (percent === 100) {
                    uploadStatus.innerText = "AI is watching (and extracting metadata)...";
                    activeBotMessageElement = createThinkingMessage();
                    setTimeout(() => {
                        progressWrapper.classList.add('hidden');
                        progressBar.style.width = '0%';
                    }, 1000);
                } else {
                    uploadStatus.innerHTML = `Uploading to Video: ${Math.round(percent)}%`;
                }
            }
        };

        // --- 3. ΜΟΛΙΣ ΑΝΕΒΕΙ ΣΤΟ CLOUDFLARE, ΕΙΔΟΠΟΙΟΥΜΕ ΤΟ RAILWAY ---
        xhr.onload = async function () {
            clearInterval(fakeInterval);
            
            if (xhr.status === 200 || xhr.status === 201) {
                
                const formData = new FormData();
                formData.append('file_key', file_key); // Στέλνουμε το όνομα του αρχείου στο Cloudflare
                if (promptText) formData.append('prompt', promptText);
                if (modeName) formData.append('mode', modeName);

                try {
                    const processRes = await fetch(`${API_BASE_URL}/upload/video`, {
                        method: 'POST',
                        headers: { 'Authorization': `Bearer ${authToken}` },
                        body: formData
                    });

                    releaseWakeLock();
                    toggleSidebarLock(false);
                    const data = await processRes.json();

                    if (processRes.ok) {
                        const session = sessions.find(s => s.id === activeSessionId);
                        if (session) {
                            session.isUploadComplete = true;
                            session.videoName = currentFileName;
                            renderSidebar();
                        }

                        if (data.metadata) currentVideoMetadata = data.metadata;
                        if (data.credits_left !== undefined) {
                            userCredits = data.credits_left;
                            const navCreditsBadge = document.getElementById('nav-credits');
                            if (navCreditsBadge) navCreditsBadge.innerHTML = `<i class="fas fa-coins"></i> ${userCredits} Credits`;
                        }

                        if (modeName === 'rough_cut' || (promptText && promptText.includes("TRASH"))) {
                            const generatedEDL = generateRobustEDL(data.answer, currentVideoMetadata, currentFileName);
                            if (generatedEDL) {
                                resolveThinkingMessage(activeBotMessageElement, `✅ **Analysis Complete**\nCreated rough cut based on technical quality rules.\nImport into Resolve using "Assist using Reel Names".`, () => createDownloadButton(generatedEDL));
                            } else {
                                resolveThinkingMessage(activeBotMessageElement, "⚠️ Logic Error: Could not generate EDL.");
                            }
                        } else {
                            resolveThinkingMessage(activeBotMessageElement, data.answer);
                        }

                        uploadArea.classList.add('hidden');
                        inputWrapper.classList.remove('hidden');
                    } else {
                        let msg = data.detail || "Server Error";
                        if (activeBotMessageElement) resolveThinkingMessage(activeBotMessageElement, "❌ Error: " + msg);
                        else addMessage('bot', "❌ Error: " + msg);
                        resetInterfaceForUpload();
                    }
                } catch (err) {
                    releaseWakeLock();
                    toggleSidebarLock(false);
                    if (activeBotMessageElement) resolveThinkingMessage(activeBotMessageElement, "❌ Processing Error.");
                    else addMessage('bot', "❌ Processing Error.");
                    resetInterfaceForUpload();
                }

            } else {
                releaseWakeLock();
                toggleSidebarLock(false);
                if (activeBotMessageElement) resolveThinkingMessage(activeBotMessageElement, "❌ Cloudflare Upload Error.");
                else addMessage('bot', "❌ Cloudflare Upload Error.");
                resetInterfaceForUpload();
            }
            activeBotMessageElement = null;
        };

        xhr.onerror = function () {
            releaseWakeLock();
            clearInterval(fakeInterval);
            toggleSidebarLock(false);
            if (activeBotMessageElement) resolveThinkingMessage(activeBotMessageElement, "❌ Network Error (Cloudflare).");
            else addMessage('bot', "❌ Network Error.");
            resetInterfaceForUpload();
            activeBotMessageElement = null;
        }

        xhr.send(fileToUpload);

    } catch (error) {
        releaseWakeLock();
        toggleSidebarLock(false);
        if (activeBotMessageElement) resolveThinkingMessage(activeBotMessageElement, "❌ Error: " + error.message);
        else addMessage('bot', "❌ Error: " + error.message);
        resetInterfaceForUpload();
        activeBotMessageElement = null;
    }
}

// ==========================================
// CHAT & IMAGE HANDLING
// ==========================================

sendBtn.addEventListener('click', sendMessage);
userInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendMessage(); });

async function sendMessage() {
    // 👇 ΝΕΟ: Έλεγχος Credits πριν στείλει μήνυμα
    if (userCredits <= 0) {
        alert("You need at least 1 credit to use the AI Assistant. Please upgrade your plan!");
        const pModal = document.getElementById('pricing-modal');
        if (pModal) pModal.classList.remove('hidden');
        return;
    }

    const text = userInput.value.trim();
    if (!text && !currentImageBase64) return;

    addMessage('user', text, currentImageBase64);

    const imageToSend = currentImageBase64;
    userInput.value = '';
    clearChatImage();

    activeBotMessageElement = createThinkingMessage();

    const endpoint = currentMode === 'video' ? '/chat/video' : '/chat/help';
    const session = sessions.find(s => s.id === activeSessionId);
    let dbProjectId = null;
    
    // Αν το session έχει μικρό νούμερο ID (όχι timestamp), είναι από τη βάση
    if (session && session.id < 1000000000000) {
        dbProjectId = session.id;
    }
    const apiHistory = session ? session.history.map(h => ({ sender: h.sender, text: h.text })) : [];

    try {
        const res = await fetch(`${API_BASE_URL}${endpoint}`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                
                // 👇👇👇 Η ΓΡΑΜΜΗ ΠΟΥ ΛΕΙΠΕΙ 👇👇👇
                'Authorization': `Bearer ${authToken}` 
                // 👆👆👆 ΧΩΡΙΣ ΑΥΤΟ, ΠΑΙΡΝΕΙΣ 401
            },
            body: JSON.stringify({ question: text, history: apiHistory, image_base64: imageToSend, project_id: dbProjectId })
        });
        const data = await res.json();

        if (res.ok) {
            resolveThinkingMessage(activeBotMessageElement, data.answer);
            if (data.credits_left !== undefined) {
                userCredits = data.credits_left;
                const navCreditsBadge = document.getElementById('nav-credits');
                if (navCreditsBadge) {
                    navCreditsBadge.innerHTML = `<i class="fas fa-coins"></i> ${userCredits} Credits`;
                }
            }
        } else {
            resolveThinkingMessage(activeBotMessageElement, "Error: " + (data.detail || "Server Error"));
        }
    } catch (err) {
        resolveThinkingMessage(activeBotMessageElement, "Network Error: " + err.message);
    }
    activeBotMessageElement = null;
}

function addMessage(sender, text, imageUrl = null, onComplete = null) {
    const session = sessions.find(s => s.id === activeSessionId);
    if (session) session.history.push({ sender, text, imageUrl, hasDownload: false });

    const div = document.createElement('div');
    div.classList.add('message', sender === 'user' ? 'user-message' : 'bot-message');
    const icon = sender === 'user' ? '<i class="fas fa-user"></i>' : '<i class="fas fa-robot"></i>';
    let contentHtml = imageUrl ? `<img src="${imageUrl}" class="chat-image"><br>` : "";

    let processedText = text;
    if (sender === 'bot') {
        processedText = formatAIResponse(text);
    }

    div.innerHTML = `<div class="avatar">${icon}</div><div class="content">${contentHtml}<p>${processedText}</p></div>`;

    if (processedText.includes('<div class="clips-grid">')) {
        div.querySelector('.content').innerHTML = contentHtml + processedText;
    }

    chatBox.appendChild(div);
    chatBox.scrollTop = chatBox.scrollHeight;

    if (sender === 'bot' && !processedText.includes('<div class="clips-grid">')) {
        let formatted = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');
        typeWriter(div.querySelector('p'), formatted, 1, onComplete);
    } else {
        if (onComplete) onComplete();
    }
}

chatUploadBtn.addEventListener('click', () => chatImageInput.click());
chatImageInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = (e) => { currentImageBase64 = e.target.result; imagePreview.src = currentImageBase64; imagePreviewContainer.classList.remove('hidden'); };
        reader.readAsDataURL(file);
    }
});
removeImageBtn.addEventListener('click', clearChatImage);
function clearChatImage() {
    currentImageBase64 = null;
    chatImageInput.value = null;
    imagePreviewContainer.classList.add('hidden');
}

// ==========================================
// 5. HELPER FUNCTIONS FOR VIRAL CLIPS (UPDATED)
// ==========================================

function formatAIResponse(text) {
    if (!text) return "";

    // 1. ΕΛΕΓΧΟΣ ΓΙΑ VIRAL CLIPS (JSON CARDS)
    const jsonRegex = /```json([\s\S]*?)```/;
    const match = text.match(jsonRegex);

    if (match) {
        try {
            const jsonString = match[1].trim();
            const data = JSON.parse(jsonString);

            if (data.viral_clips) {
                let cardsHtml = '<div class="clips-grid">';
                data.viral_clips.forEach((clip, index) => {
                    const btnId = `btn-cut-${index}`;
                    
                    let btnText = "Create & Download";
                    let btnIcon = "fa-download";
                    
                    if (clip.render_style === 'screenshot' || clip.title.toLowerCase().includes('thumbnail')) {
                        btnText = "📸 Save Screenshot";
                        btnIcon = "fa-camera";
                    } else if (clip.render_style === 'gif') {
                        btnText = "🎞️ Create GIF";
                        btnIcon = "fa-film";
                    } else if (clip.render_style === 'audio') {
                        btnText = "🎵 Download MP3";
                        btnIcon = "fa-music";
                    } else if (clip.render_style === 'mute') {
                        btnText = "🔇 Save Muted Video";
                        btnIcon = "fa-volume-mute";
                    }

                    cardsHtml += `
                    <div class="clip-card">
                        <div class="clip-header">
                           <span class="clip-time">⏱ ${clip.start} - ${clip.end}</span>
                        </div>
                        <div class="clip-title">${clip.title}</div>
                        <div class="clip-caption">"${clip.reason || clip.caption}"</div>
                        <div class="clip-hashtags">${clip.hashtags || ''}</div>
                        <button id="${btnId}" class="btn-viral-dl" onclick="downloadClip('${clip.start}', '${clip.end}', ${index + 1}, '${btnId}')">
                            <i class="fas ${btnIcon}"></i> ${btnText}
                        </button>
                    </div>`;
                });
                cardsHtml += '</div>';
                return text.replace(jsonRegex, cardsHtml);
            }
        } catch (e) {
            console.error("JSON Error:", e);
        }
    }

    // 2. ΜΟΡΦΟΠΟΙΗΣΗ ΚΕΙΜΕΝΟΥ (Αν δεν είναι κάρτες)
    // Εδώ φτιάχνουμε τα Bold, τα Headings και τα Enter
    
    let formatted = text;

    // Headers
    formatted = formatted.replace(/^### (.*$)/gm, '<h3>$1</h3>');
    formatted = formatted.replace(/^## (.*$)/gm, '<h2>$1</h2>');

    // Bold (**text**)
    formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

    // Bullet Points
    formatted = formatted.replace(/^\* (.*$)/gm, '• $1');

    // Newlines (Enter -> <br>)
    // Αυτό είναι που έλειπε και τα έδειχνε όλα σε μια γραμμή!
    formatted = formatted.replace(/\n/g, '<br>');

    return formatted;
}

async function downloadClip(start, end, index, btnId) {
    const btn = document.getElementById(btnId);
    if (!btn) return;

    // Κρατάμε το αρχικό κείμενο του κουμπιού
    const originalHtml = btn.innerHTML;
    
    // Αλλάζουμε το κουμπί σε "Processing"
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing... (wait here)';
    btn.style.background = "#555";
    btn.style.cursor = "wait";
    if (typeof requestWakeLock === "function") requestWakeLock();

    try {
        const response = await fetch(`${API_BASE_URL}/render/clip`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ start_time: start, end_time: end, index: index })
        });

        if (response.ok) {
            const blob = await response.blob(); // Παίρνουμε το αρχείο
            btn.innerHTML = '<i class="fas fa-cloud-download-alt fa-bounce"></i> Downloading...';

            // 👇 ΝΕΟ: Βρίσκουμε τη σωστή κατάληξη ανάλογα με τον τύπο του αρχείου (MIME type)
            let extension = "mp4"; // Default
            if (blob.type === "image/jpeg" || blob.type === "image/jpg") extension = "jpg";
            else if (blob.type === "image/gif") extension = "gif";
            else if (blob.type === "audio/mpeg" || blob.type === "audio/mp3") extension = "mp3";

            const downloadUrl = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = downloadUrl;
            a.download = `clip_${index}.${extension}`; // <--- Τώρα παίρνει τη σωστή κατάληξη!
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(downloadUrl);

            setTimeout(() => {
                btn.disabled = false;
                btn.innerHTML = originalHtml;
                btn.style.background = '';
                btn.style.cursor = 'pointer';
            }, 1000);
        } else {
            // Αν ο server στείλει σφάλμα, το διαβάζουμε ως κείμενο
            const errorText = await response.text();
            throw new Error(errorText || "Server Error");
        }
    } catch (error) {
        console.error(error);
        btn.innerHTML = 'Error';
        btn.style.background = '#e74c3c';
        btn.disabled = false;
        // Εδώ έσκαγε το JSON error. Τώρα θα δείχνει το πραγματικό μήνυμα.
        alert("Download Failed: " + error.message);
    }
    
    finally {
        // --- ΠΡΟΣΘΗΚΗ 3: Ελευθέρωσε την οθόνη ---
        if (typeof releaseWakeLock === "function") releaseWakeLock();
    }
}
// ==========================================
// 🔐 AUTHENTICATION LOGIC (LOGIN / REGISTER)
// ==========================================

// 1. ΕΛΕΓΧΟΣ ΚΑΤΑ ΤΗΝ ΕΚΚΙΝΗΣΗ
function checkAuth() {
    if (!authToken) {
        // Αν ΔΕΝ είμαστε συνδεδεμένοι:
        loginBtnNav.textContent = "Login";
        navCredits.style.display = 'none'; // Κρύψε τα credits
        
        loginBtnNav.onclick = (e) => {
            e.preventDefault(); 
            authModal.classList.remove('hidden');
        };
    } else {
        // Αν ΕΙΜΑΣΤΕ συνδεδεμένοι:
        loginBtnNav.textContent = "Sign Out";
        navCredits.style.display = 'inline'; // Εμφάνισε τα credits
        
        loginBtnNav.onclick = (e) => {
            e.preventDefault();
            logout();
        };
        fetchUserProfile(); // Φέρε το νούμερο
    }
}

// 2. FETCH USER PROFILE (ΓΙΑ CREDITS)
// 2. FETCH USER PROFILE (ΓΙΑ CREDITS)
async function fetchUserProfile() {
    try {
        const resUser = await fetch(`${API_BASE_URL}/users/me`, {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        
        if (resUser.ok) {
            const userData = await resUser.json();
            userCredits = userData.credits;
            userPlan = userData.plan;
            isPremiumUser = userData.is_premium;
            if(navCredits) navCredits.innerHTML = `<i class="fas fa-coins"></i> ${userCredits} Credits`;
            
            // --- 👇 Η ΝΕΑ ΛΟΓΙΚΗ ΓΙΑ ΤΑ ΚΟΥΜΠΙΑ ΣΤΟ NAVBAR 👇 ---
            const manageSubBtn = document.getElementById('manage-sub-btn');
            const pricingLink = document.getElementById('pricing-link');

            if (userData.is_premium) {
                // ΕΙΝΑΙ ΕΝΕΡΓΟΣ ΣΥΝΔΡΟΜΗΤΗΣ: Δείξε Manage, Κρύψε Pricing
                if (manageSubBtn) manageSubBtn.style.display = 'inline-block';
                if (pricingLink) pricingLink.style.display = 'none';
            } else {
                // ΔΕΝ ΕΙΝΑΙ ΣΥΝΔΡΟΜΗΤΗΣ (ή ακύρωσε): Κρύψε Manage, Δείξε Pricing
                if (manageSubBtn) manageSubBtn.style.display = 'none';
                if (pricingLink) pricingLink.style.display = 'inline-block';

                // Αν είναι ΠΑΛΙΟΣ πελάτης (ακύρωσε), του βγάζουμε τις κανονικές τιμές χωρίς προσφορές!
                if (userData.had_subscription) {
                    adjustPricingForReturningUser();
                }
            }
            // ----------------------------------------------------

            await loadUserHistory(); 
            
        } else {
            logout();
        }
    } catch (e) { logout(); }
}

// 👇 ΝΕΑ ΣΥΝΑΡΤΗΣΗ ΠΟΥ ΔΙΟΡΘΩΝΕΙ ΤΟ PRICING MODAL 👇
function adjustPricingForReturningUser() {
    // Κρύβει την κόκκινη μπάρα της προσφοράς πάνω-πάνω
    const promoBanner = document.getElementById('promo-banner');
    if (promoBanner) promoBanner.style.display = 'none';

    // Αλλάζει την τιμή του Creator σε καθαρό 8€
    const creatorDisplay = document.getElementById('creator-price-display');
    if (creatorDisplay) creatorDisplay.innerHTML = '€8.00<span style="font-size: 1rem; color: var(--text-muted);">/mo</span>';
    
    // Αλλάζει την τιμή του Pro σε καθαρό 16€
    const proDisplay = document.getElementById('pro-price-display');
    if (proDisplay) proDisplay.innerHTML = '€16.00<span style="font-size: 1rem; color: var(--text-muted);">/mo</span>';

    // Καθαρίζει τα γραμματάκια από κάτω ("Then €8.00...")
    const creatorSubtext = document.getElementById('creator-subtext');
    if (creatorSubtext) creatorSubtext.innerHTML = 'Cancel anytime.';

    const proSubtext = document.getElementById('pro-subtext');
    if (proSubtext) proSubtext.innerHTML = 'Cancel anytime.';
}

// --- ΝΕΑ ΣΥΝΑΡΤΗΣΗ: LOAD HISTORY ---
async function loadUserHistory() {
    try {
        const res = await fetch(`${API_BASE_URL}/my-projects`, {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        
        if (res.ok) {
            const projects = await res.json();
            
            // 1. Καθαρίζουμε τελείως τη λίστα για να τη γεμίσουμε από τη βάση
            sessions = []; 
            
            projects.forEach(proj => {
                const newSession = {
                    id: proj.id,
                    // Αν το mode είναι 'chat', το type στο JS είναι 'help' (για να ανοίγει το expert agent)
                    type: proj.mode === 'chat' ? 'help' : 'video', 
                    title: proj.filename,
                    videoName: proj.filename,
                    history: [],
                    isUploadComplete: (proj.status === 'completed'),
                    isPinned: false
                };

                // 2. ΕΔΩ ΕΙΝΑΙ Η ΔΙΟΡΘΩΣΗ: Πώς διαβάζουμε το ιστορικό
                if (proj.ai_response) {
                    // Περίπτωση CHAT: Το ai_response είναι JSON λίστα με μηνύματα
                    if (proj.mode === 'chat') {
                        try {
                            const rawHistory = JSON.parse(proj.ai_response);
                            // Μετατροπή στο format που θέλει το Frontend
                            newSession.history = rawHistory.map(h => ({
                                sender: h.sender,
                                text: h.text,
                                hasDownload: false
                            }));
                        } catch (e) { console.log("Chat history parse error", e); }
                    } 
                    // Περίπτωση VIDEO: Το ai_response είναι απλό κείμενο
                    else {
                        newSession.history.push({
                            sender: 'bot',
                            text: proj.ai_response,
                            hasDownload: false
                        });
                    }
                } else if (proj.status === 'processing') {
                     newSession.history.push({
                        sender: 'bot',
                        text: "⚠️ This project is still processing...",
                        hasDownload: false
                    });
                }
                
                sessions.push(newSession);
            });
            
            // Αν δεν έχουμε κανένα session, φτιάχνουμε ένα κενό για να μην είναι άδειο το UI
            if (sessions.length === 0) {
                 createNewSession(); 
            } else {
                // Φορτώνουμε το τελευταίο (προαιρετικό, αν θες να ανοίγει το τελευταίο chat)
                // activeSessionId = sessions[0].id;
                // switchSession(activeSessionId);
            }
            
            renderSidebar();
        }
    } catch (e) {
        console.error("Failed to load history:", e);
    }
}

// 3. LOGOUT FUNCTION
function logout() {
    localStorage.removeItem('access_token'); // Σβήσιμο token
    authToken = null;
    userCredits = 0;
    window.location.reload(); // Refresh για να καθαρίσουν όλα
}


// 4. LOGIN CLICK EVENT
btnLogin.addEventListener('click', async () => {
    const email = authEmail.value;
    const password = authPass.value;
    
    // Καθαρισμός παλιών μηνυμάτων λάθους
    authError.innerText = "";
    btnLogin.innerText = "Verifying...";

    // Το FastAPI στο Login θέλει Form Data, όχι JSON
    const formData = new URLSearchParams();
    formData.append('username', email); 
    formData.append('password', password);

    try {
        const res = await fetch(`${API_BASE_URL}/token`, {
            method: 'POST',
            body: formData // Στέλνουμε form data
        });
        
        const data = await res.json();
        
        if (res.ok) {
            // ΕΠΙΤΥΧΙΑ!
            localStorage.setItem('access_token', data.access_token);
            authToken = data.access_token;
            authModal.classList.add('hidden');
            checkAuth(); // Ενημέρωσε το UI
            btnLogin.innerText = "Log In";
        } else {
            // ΛΑΘΟΣ (π.χ. λάθος κωδικός)
            authError.innerText = "❌ " + (data.detail || "Login failed");
            btnLogin.innerText = "Log In";
        }
    } catch (e) {
        authError.innerText = "❌ Connection Error";
        btnLogin.innerText = "Log In";
    }
});

// 5. REGISTER CLICK EVENT
btnRegister.addEventListener('click', async () => {
    const email = authEmail.value;
    const password = authPass.value;
    
    authError.innerText = "";
    btnRegister.innerText = "Creating...";

    try {
        const res = await fetch(`${API_BASE_URL}/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        
        const data = await res.json();
        
        if (res.ok) {
            // ΕΠΙΤΥΧΙΑ!
            alert("✅ Account created successfully! You have 3 Free Credits.\nPlease Log In now.");
            // Απλά κάνουμε trigger το login για ευκολία, ή περιμένουμε τον χρήστη
            btnRegister.innerText = "Create Free Account";
            authEmail.focus(); // Πήγαινε τον κέρσορα στο email
        } else {
            authError.innerText = "❌ " + (data.detail || "Registration failed");
            btnRegister.innerText = "Create Free Account";
        }
    } catch (e) {
        authError.innerText = "❌ Connection Error";
        btnRegister.innerText = "Create Free Account";
    }
});

// Ξεκίνα τον έλεγχο μόλις φορτώσει η σελίδα
checkAuth();

// --- ΝΕΑ ΛΟΓΙΚΗ: AI COLORIST ---

// Προσθήκη του click event για την 3η κάρτα (AI Colorist)
document.getElementById('btn-colorist').addEventListener('click', () => {
    setupMode('colorist');
});

// Επεκτείνουμε το υπάρχον setupMode για να χειρίζεται το νέο UI
// Επεκτείνουμε το υπάρχον setupMode για να χειρίζεται το νέο UI
// Επεκτείνουμε το υπάρχον setupMode για να χειρίζεται το νέο UI
const originalSetupMode = setupMode; 
window.setupMode = function(mode) {
    originalSetupMode(mode); 
    
    // Πιάνουμε όλα τα στοιχεία
    const uploadArea = document.getElementById('upload-area');
    const inputWrapper = document.querySelector('.input-wrapper');
    const coloristArea = document.getElementById('colorist-area');
    const sidebar = document.querySelector('.chat-sidebar'); 
    const chatBox = document.getElementById('chat-box'); // <-- Πιάνουμε το ιστορικό του chat
    const chatHeader = document.querySelector('.chat-header'); // <-- Πιάνουμε τον τίτλο
    
    // Κρύβουμε τα βασικά
    uploadArea.classList.add('hidden');
    inputWrapper.classList.add('hidden');
    coloristArea.classList.add('hidden');
    
    // ΕΠΑΝΑΦΟΡΑ: Στα άλλα modes, θέλουμε να φαίνονται κανονικά!
    if (sidebar) sidebar.classList.remove('hidden');
    if (chatBox) chatBox.classList.remove('hidden');
    if (chatHeader) chatHeader.classList.remove('hidden');

    if (mode === 'video') {
        uploadArea.classList.remove('hidden');
        if (chatHeader) document.getElementById('mode-title').innerText = "Media Intelligence";
    } else if (mode === 'help') {
        inputWrapper.classList.remove('hidden');
        if (chatHeader) document.getElementById('mode-title').innerText = "Resolve Expert";
    } else if (mode === 'colorist') {
        coloristArea.classList.remove('hidden');
        
        // ΕΞΑΦΑΝΙΣΗ: Κρύβουμε ΟΛΑ τα άσχετα στοιχεία για να μην "φεγγίζουν" από πίσω
        if (sidebar) sidebar.classList.add('hidden');
        if (chatBox) chatBox.classList.add('hidden');
        if (chatHeader) chatHeader.classList.add('hidden');
        
        // Reset του workspace
        document.getElementById('colorist-upload-box').classList.remove('hidden');
        document.getElementById('colorist-workspace').classList.add('hidden');
        document.getElementById('colorist-results').innerHTML = "";

        const showcase = document.getElementById('colorist-workflow-showcase');
        if (showcase) showcase.classList.remove('hidden');
    }
};

let coloristImageBase64 = null;

// Διαχείριση ανεβάσματος εικόνας
document.getElementById('colorist-image-input').addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = (e) => { 
            coloristImageBase64 = e.target.result; 
            document.getElementById('colorist-preview').src = coloristImageBase64;
            document.getElementById('colorist-upload-box').classList.add('hidden');
            document.getElementById('colorist-workspace').classList.remove('hidden');
            document.getElementById('colorist-results').innerHTML = ""; // Καθαρισμός παλιών αποτελεσμάτων

            const showcase = document.getElementById('colorist-workflow-showcase');
            if (showcase) showcase.classList.add('hidden');
        };
        reader.readAsDataURL(file);
    }
});

// Η λειτουργία που καλεί το API
// --- STATE ΓΙΑ ΤΟ LOG MODE ---
let isLogMode = false;

// Συνάρτηση που θα καλείται από το HTML για να αλλάζει από Rec709 σε Log
window.toggleLogMode = function(enableLog) {
    isLogMode = enableLog;
    
    const styleContainer = document.getElementById('colorist-styles-container');
    const logContainer = document.getElementById('colorist-log-container');
    const modeToggleBtn = document.getElementById('btn-toggle-log');

    if (enableLog) {
        if(styleContainer) styleContainer.classList.add('hidden');
        if(logContainer) logContainer.classList.remove('hidden');
        if(modeToggleBtn) {
            modeToggleBtn.innerHTML = '<i class="fas fa-video"></i> Switch to Standard (Rec.709)';
            modeToggleBtn.classList.add('log-active');
        }
    } else {
        if(styleContainer) styleContainer.classList.remove('hidden');
        if(logContainer) logContainer.classList.add('hidden');
        if(modeToggleBtn) {
            modeToggleBtn.innerHTML = '<i class="fas fa-film"></i> I have LOG Footage';
            modeToggleBtn.classList.remove('log-active');
        }
    }
}

// Η ΑΝΑΒΑΘΜΙΣΜΕΝΗ λειτουργία που καλεί το API
async function generateColorGrade(selection) {
    // Το 'selection' τώρα μπορεί να είναι Style (π.χ. 'Cinematic') Ή Κάμερα (π.χ. 'S-Log3')
    
    if (!authToken) {
        authModal.classList.remove('hidden');
        authError.style.color = "#fbbf24";
        authError.innerText = "⚡ Please log in First !";
        return; 
    }
    
    if (userCredits < 2) {
        alert("You run out of credits !!! 2 credits are required to generate a grade.");
        const pricingModal = document.getElementById('pricing-modal');
        if (pricingModal) pricingModal.classList.remove('hidden');
        return; 
    }

    const resultsDiv = document.getElementById('colorist-results');
    resultsDiv.innerHTML = `<div style="text-align: center; color: var(--primary); padding: 40px;"><i class="fas fa-spinner fa-spin fa-2x"></i><p style="margin-top: 15px;">Analyzing ${isLogMode ? 'LOG footage' : 'Colors'} for ${selection}...</p></div>`;
    
    // Ετοιμάζουμε τα δεδομένα δυναμικά
    let requestStyle = "Natural Fix"; // Default για αποφυγή λαθών
    let requestCamera = "";

    if (isLogMode) {
        requestCamera = selection; // Αν είναι Log, η επιλογή είναι η Κάμερα
    } else {
        requestStyle = selection;  // Αν είναι Rec709, η επιλογή είναι το Style
    }

    try {
        const res = await fetch(`${API_BASE_URL}/api/color-grade`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}` 
            },
            body: JSON.stringify({ 
                image_base64: coloristImageBase64, 
                style: requestStyle,
                is_log: isLogMode,               // Το στέλνουμε στην Python!
                camera_profile: requestCamera    // Το στέλνουμε στην Python!
            })
        });
        
        const data = await res.json();
        
        if (res.ok) {
            // Ενημέρωση Credits
            if (data.credits_left !== undefined) {
                userCredits = data.credits_left;
                document.getElementById('nav-credits').innerHTML = `<i class="fas fa-coins"></i> ${userCredits} Credits`;
            }
            
            // Ζωγραφίζουμε τα αποτελέσματα!
            renderColorWheels(data.result.color_grade, resultsDiv);
            resultsDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } else {
            resultsDiv.innerHTML = `<p style="color: #ff6b6b; text-align: center;">Error: ${data.detail || 'Failed'}</p>`;
        }
    } catch (e) {
        resultsDiv.innerHTML = `<p style="color: #ff6b6b; text-align: center;">Network Error</p>`;
    }
}


// Συνάρτηση που φτιάχνει και κατεβάζει το CDL
function downloadCDL(cdlData) {
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<ColorDecisionList xmlns="urn:ASC:CDL:v1.01">
    <ColorDecision>
        <ColorCorrection id="VinciCut_Grade">
            <SOPNode>
                <Slope>${cdlData.slope.R.toFixed(4)} ${cdlData.slope.G.toFixed(4)} ${cdlData.slope.B.toFixed(4)}</Slope>
                <Offset>${cdlData.offset.R.toFixed(4)} ${cdlData.offset.G.toFixed(4)} ${cdlData.offset.B.toFixed(4)}</Offset>
                <Power>${cdlData.power.R.toFixed(4)} ${cdlData.power.G.toFixed(4)} ${cdlData.power.B.toFixed(4)}</Power>
            </SOPNode>
            <SatNode>
                <Saturation>${cdlData.saturation.toFixed(4)}</Saturation>
            </SatNode>
        </ColorCorrection>
    </ColorDecision>
</ColorDecisionList>`;

    const blob = new Blob([xml], { type: 'text/xml' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `VinciCut_Look_${Date.now()}.cc`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
}

// Το Νέο CDL-First UI
// Το Νέο CDL-First UI με το σωστό Color Slice Panel!
function renderColorWheels(cg, container) {
    // Αν το AI δεν έστειλε τη νέα δομή (fallback για παλιά chats), μην κρασάρεις
    if (!cg.cdl) {
        container.innerHTML = `<div style="color: #ef4444; padding: 20px;">⚠️ Please start a New Grade. The AI system has been upgraded to support CDL workflows.</div>`;
        return;
    }

    // Υπολογισμός για τα sliders του Color Slice (για να κουνιούνται οι βούλες)
    const slice = cg.color_slice || { Den: 0.00, Sat: 1.00, Hue: 0.00 };
    // Saturation range: 0.00 to 2.00 (1.00 is 50% / center)
    const satPos = (slice.Sat / 2) * 100; 
    // Density range: -1.00 to 1.00 (0.00 is 50% / center)
    const denPos = ((slice.Den + 1) / 2) * 100;

    // 👉 ΕΛΕΓΧΟΣ: Δείχνουμε το Finishing Touches ΜΟΝΟ στο Rec.709
    let finishingTouchesHtml = "";
    if (!isLogMode) {
        finishingTouchesHtml = `
        <div style="background: #1f2937; border: 1px solid #374151; border-radius: 12px; padding: 20px; margin-top: 20px;">
            <h3 style="margin-top: 0; color: #fbbf24;"><i class="fas fa-sliders-h"></i> Finishing Touches (Manual)</h3>
            <p style="font-size: 0.85rem; color: #9ca3af; margin-bottom: 15px;">
                CDL files do not support these parameters. Apply them manually in your Color Page.
            </p>

            <div style="display: flex; justify-content: space-around; flex-wrap: wrap; gap: 15px; margin-bottom: 20px;">
                <div style="background: #111827; padding: 15px; border-radius: 8px; min-width: 120px; text-align: center;">
                    <span style="color: #9ca3af; font-size: 0.85rem;">Contrast</span><br>
                    <strong style="font-size: 1.2rem; color: white;">${cg.sliders.contrast.toFixed(2)}</strong>
                </div>
                <div style="background: #111827; padding: 15px; border-radius: 8px; min-width: 120px; text-align: center;">
                    <span style="color: #9ca3af; font-size: 0.85rem;">Temperature</span><br>
                    <strong style="font-size: 1.2rem; color: white;">${cg.sliders.temperature > 0 ? '+' : ''}${cg.sliders.temperature}</strong>
                </div>
            </div>

            <div class="cs-panel" style="background: #111827; border: 1px solid #374151; padding: 15px; border-radius: 8px;">
                <div class="cs-header" style="color: #9ca3af; font-size: 0.85rem; display: block; margin-bottom: 15px;">
                    <i class="fas fa-layer-group"></i> COLOR SLICE PANEL
                </div>

                <div style="text-align: center; margin-bottom: 20px;">
                    <img src="resolve_colorslice_guide.png" alt="Locate Color Slice Panel" style="max-width: 100%; border-radius: 8px; border: 1px solid #374151; box-shadow: 0 4px 10px rgba(0,0,0,0.4);">
                </div>

                <div class="cs-vectors">
                    <span>Vectors</span>
                    <div class="cs-vec-color" style="background: #ff3b30;">Red</div>
                    <div class="cs-vec-color" style="background: #ffcc00; color: black;">Yellow</div>
                    <div class="cs-vec-color" style="background: #4cd964; color: black;">Green</div>
                    <div class="cs-vec-color" style="background: #5ac8fa; color: black;">Cyan</div>
                    <div class="cs-vec-color" style="background: #007aff;">Blue</div>
                    <div class="cs-vec-color" style="background: #ff2d55;">Magenta</div>
                </div>

                <div class="cs-controls">
                    <div class="cs-control-row">
                        <span>Hue</span>
                        <div class="cs-slider-track"><div class="cs-slider-thumb" style="left: 50%;"></div></div>
                        <span class="cs-val">${slice.Hue.toFixed(2)}</span>
                    </div>
                    <div class="cs-control-row">
                        <span>Sat</span>
                        <div class="cs-slider-track"><div class="cs-slider-thumb" style="left: ${satPos}%;"></div></div>
                        <span class="cs-val">${slice.Sat.toFixed(2)}</span>
                    </div>
                    <div class="cs-control-row">
                        <span>Den</span>
                        <div class="cs-slider-track"><div class="cs-slider-thumb" style="left: ${denPos}%;"></div></div>
                        <span class="cs-val">${slice.Den.toFixed(2)}</span>
                    </div>
                </div>
            </div>
        </div>`;
    }

    let html = `<div class="cg-container">
        <div class="cg-advice" style="background: rgba(16, 185, 129, 0.1); border-left: 4px solid #10b981; padding: 15px; margin-bottom: 20px;">
            <strong style="color: #10b981;">💡 AI Colorist Note:</strong><br>
            ${cg.advice}
        </div>
        
        <div style="background: #1f2937; border: 1px solid #374151; border-radius: 12px; padding: 20px; margin-top: 20px;">
            <h3 style="margin-top: 0; color: #10b981;"><i class="fas fa-file-code"></i> Base Grade (ASC CDL)</h3>
            <p style="font-size: 0.85rem; color: #9ca3af; margin-bottom: 15px;">
                Add a <strong>CDL Transform</strong> node in Resolve and load this file. It sets your Slope, Offset, Power, and Saturation instantly.
            </p>
            
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; text-align: center; margin-bottom: 20px;">
                <div style="background: #111827; padding: 10px; border-radius: 8px;">
                    <span style="color: #9ca3af; font-size: 0.8rem;">SLOPE (Gain)</span><br>
                    <span style="color: #ef4444;">R: ${cg.cdl.slope.R.toFixed(2)}</span> | 
                    <span style="color: #22c55e;">G: ${cg.cdl.slope.G.toFixed(2)}</span> | 
                    <span style="color: #3b82f6;">B: ${cg.cdl.slope.B.toFixed(2)}</span>
                </div>
                <div style="background: #111827; padding: 10px; border-radius: 8px;">
                    <span style="color: #9ca3af; font-size: 0.8rem;">POWER (Gamma)</span><br>
                    <span style="color: #ef4444;">R: ${cg.cdl.power.R.toFixed(2)}</span> | 
                    <span style="color: #22c55e;">G: ${cg.cdl.power.G.toFixed(2)}</span> | 
                    <span style="color: #3b82f6;">B: ${cg.cdl.power.B.toFixed(2)}</span>
                </div>
                <div style="background: #111827; padding: 10px; border-radius: 8px;">
                    <span style="color: #9ca3af; font-size: 0.8rem;">OFFSET</span><br>
                    <span style="color: #ef4444;">R: ${cg.cdl.offset.R.toFixed(2)}</span> | 
                    <span style="color: #22c55e;">G: ${cg.cdl.offset.G.toFixed(2)}</span> | 
                    <span style="color: #3b82f6;">B: ${cg.cdl.offset.B.toFixed(2)}</span>
                </div>
                <div style="background: #111827; padding: 10px; border-radius: 8px;">
                    <span style="color: #9ca3af; font-size: 0.8rem;">SATURATION</span><br>
                    <strong style="font-size: 1.2rem; color: white;">${cg.cdl.saturation.toFixed(2)}</strong>
                </div>
            </div>

            <div style="text-align: center;">
                <button id="btn-download-cdl" class="action-btn" style="background: #10b981; border: none; padding: 10px 20px; font-weight: bold; border-radius: 8px; color: white; cursor: pointer; box-shadow: 0 4px 10px rgba(16, 185, 129, 0.3);">
                    <i class="fas fa-download"></i> Download .CDL File
                </button>
            </div>
        </div>

        ${finishingTouchesHtml}

        <div style="text-align: center; margin-top: 25px;">
            <button class="action-btn" style="display: inline-block; background: transparent; border: 1px solid #374151; padding: 10px 20px; font-weight: bold; border-radius: 8px; color: white; cursor: pointer;" onclick="document.getElementById('colorist-upload-box').classList.remove('hidden'); document.getElementById('colorist-workspace').classList.add('hidden'); document.getElementById('colorist-results').innerHTML=''; document.getElementById('colorist-workflow-showcase').classList.remove('hidden');">
                <i class="fas fa-redo"></i> Grade Another Image
            </button>
        </div>
    </div>`;

    container.innerHTML = html;

    // Προσθήκη του Event Listener στο κουμπί Download
    document.getElementById('btn-download-cdl').addEventListener('click', () => {
        downloadCDL(cg.cdl);
    });
}

// ==========================================
// 💳 STRIPE PAYMENTS & PRICING
// ==========================================

const pricingLink = document.getElementById('pricing-link');
const pricingModal = document.getElementById('pricing-modal');

// Άνοιγμα του Pricing
if(pricingLink) {
    pricingLink.addEventListener('click', (e) => {
        e.preventDefault();
        pricingModal.classList.remove('hidden');
    });
}

// Συνάρτηση Αγοράς Συνδρομής
async function buyPlan(planName) {
    if (!authToken) {
        alert("Please log in or create an account first!");
        pricingModal.classList.add('hidden');
        authModal.classList.remove('hidden');
        return;
    }

    const btn = event.target;
    const originalText = btn.innerText;
    btn.innerText = "Processing...";
    btn.disabled = true;

    try {
        const response = await fetch(`${API_BASE_URL}/create-checkout-session`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}` 
            },
            body: JSON.stringify({ plan: planName })
        });

        if (response.ok) {
            const data = await response.json();
            // Ανακατεύθυνση στη σελίδα της Stripe
            window.location.href = data.checkout_url; 
        } else {
            alert("Error connecting to payment provider. Please try again later.");
            btn.innerText = originalText;
            btn.disabled = false;
        }
    } catch (e) {
        alert("Network error.");
        btn.innerText = originalText;
        btn.disabled = false;
    }
}


// Έλεγχος αν γύρισε από επιτυχημένη πληρωμή
window.addEventListener('load', () => {
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('payment') === 'success') {
        alert("🎉 Payment Successful! Your credits have been updated.");
        // Καθαρίζουμε το URL για να μην ξαναβγάλει το alert
        window.history.replaceState({}, document.title, window.location.pathname);
    }
    if (urlParams.get('payment') === 'cancelled') {
        alert("Payment was cancelled.");
        window.history.replaceState({}, document.title, window.location.pathname);
    }
});
// ==========================================
// 📧 EMAIL VERIFICATION & FORGOT PASSWORD
// ==========================================

const forgotLink = document.getElementById('forgot-password-link');
const forgotModal = document.getElementById('forgot-modal');
const btnSendReset = document.getElementById('btn-send-reset');
const forgotEmail = document.getElementById('forgot-email');
const forgotMessage = document.getElementById('forgot-message');

const resetModal = document.getElementById('reset-modal');
const btnSavePassword = document.getElementById('btn-save-password');
const newPasswordInput = document.getElementById('new-password');
const resetMessage = document.getElementById('reset-message');

let currentResetToken = null;

// 1. Άνοιγμα του Forgot Password Modal
if (forgotLink) {
    forgotLink.addEventListener('click', (e) => {
        e.preventDefault();
        authModal.classList.add('hidden'); // Κλείνουμε το login
        forgotModal.classList.remove('hidden'); // Ανοίγουμε το forgot
    });
}

// 2. Αποστολή του Email (Στο backend)
if (btnSendReset) {
    btnSendReset.addEventListener('click', async () => {
        const email = forgotEmail.value.trim();
        if (!email) return;

        btnSendReset.innerText = "Sending...";
        forgotMessage.innerText = "";

        try {
            const res = await fetch(`${API_BASE_URL}/forgot-password?email=${encodeURIComponent(email)}`, {
                method: 'POST'
            });
            const data = await res.json();
            
            forgotMessage.style.color = "#10b981"; // Πράσινο
            forgotMessage.innerText = "✅ " + data.message;
            btnSendReset.innerText = "Send Link";
        } catch (e) {
            forgotMessage.style.color = "#ff6b6b";
            forgotMessage.innerText = "❌ Network Error";
            btnSendReset.innerText = "Send Link";
        }
    });
}

// 3. Αποθήκευση Νέου Κωδικού
if (btnSavePassword) {
    btnSavePassword.addEventListener('click', async () => {
        const newPass = newPasswordInput.value;
        if (newPass.length < 6) {
            resetMessage.style.color = "#ff6b6b";
            resetMessage.innerText = "❌ Password must be at least 6 characters.";
            return;
        }

        btnSavePassword.innerText = "Saving...";
        try {
            const res = await fetch(`${API_BASE_URL}/reset-password`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token: currentResetToken, new_password: newPass })
            });
            const data = await res.json();

            if (res.ok) {
                resetMessage.style.color = "#10b981";
                resetMessage.innerText = "✅ " + data.message;
                btnSavePassword.style.display = 'none';
                
                // Μετά από 2 δευτερόλεπτα, κλείνει και ανοίγει το login
                setTimeout(() => {
                    resetModal.classList.add('hidden');
                    window.history.replaceState({}, document.title, window.location.pathname); // Καθαρίζει το URL
                    authModal.classList.remove('hidden');
                }, 2000);
            } else {
                resetMessage.style.color = "#ff6b6b";
                resetMessage.innerText = "❌ " + (data.detail || "Error");
                btnSavePassword.innerText = "Save Password";
            }
        } catch (e) {
            resetMessage.style.color = "#ff6b6b";
            resetMessage.innerText = "❌ Network Error";
            btnSavePassword.innerText = "Save Password";
        }
    });
}

// 4. ΑΥΤΟΜΑΤΟΣ ΕΛΕΓΧΟΣ URL ΟΤΑΝ ΦΟΡΤΩΝΕΙ Η ΣΕΛΙΔΑ
window.addEventListener('load', async () => {
    const urlParams = new URLSearchParams(window.location.search);
    
    // --- ΠΕΡΙΠΤΩΣΗ Α: Ο χρήστης πάτησε το link επιβεβαίωσης email ---
    if (urlParams.has('verify')) {
        const token = urlParams.get('verify');
        try {
            const res = await fetch(`${API_BASE_URL}/verify-email?token=${token}`, { method: 'POST' });
            const data = await res.json();
            
            if (res.ok) {
                alert("🎉 " + data.message);
                window.history.replaceState({}, document.title, window.location.pathname); // Καθαρίζει το URL
                authModal.classList.remove('hidden'); // Του ανοίγει να κάνει login!
            } else {
                alert("❌ " + (data.detail || "Invalid or expired link."));
            }
        } catch(e) {
            alert("❌ Network Error connecting to server.");
        }
    }

    // --- ΠΕΡΙΠΤΩΣΗ Β: Ο χρήστης πάτησε το link αλλαγής κωδικού ---
    if (urlParams.has('reset')) {
        currentResetToken = urlParams.get('reset');
        resetModal.classList.remove('hidden'); // Ανοίγει κατευθείαν το παραθυράκι αλλαγής κωδικού
    }
});