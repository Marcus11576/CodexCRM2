/**
 * Antigravity CRM - Global Background Manager
 * Persists backdrop preferences locally and supports page-specific profile imagery.
 */
(function () {
    const STORAGE_KEY = 'antigravity.background.v1';
    const DEFAULT_MODE = 'daily';
    const DEFAULTS = {
        mode: DEFAULT_MODE,
        customImage: '',
        profilePhotoPages: ['profile']
    };
    const DAILY_BACKGROUNDS = [
        'https://images.unsplash.com/photo-1451187580459-43490279c0fa?q=80&w=2072&auto=format&fit=crop',
        'https://images.unsplash.com/photo-1446776811953-b23d57bd21aa?q=80&w=2072&auto=format&fit=crop',
        'https://images.unsplash.com/photo-1464802686167-b939a6910659?q=80&w=2070&auto=format&fit=crop',
        'https://images.unsplash.com/photo-1506744038136-46273834b3fb?q=80&w=2070&auto=format&fit=crop',
        'https://images.unsplash.com/photo-1470071459604-3b5ec3a7fe05?q=80&w=2074&auto=format&fit=crop',
        'https://images.unsplash.com/photo-1441974231531-c6227db76b6e?q=80&w=2071&auto=format&fit=crop',
        'https://images.unsplash.com/photo-1501785888041-af3ef285b470?q=80&w=2070&auto=format&fit=crop',
        'https://images.unsplash.com/photo-1493246507139-91e8bef99c02?q=80&w=2070&auto=format&fit=crop',
        'https://images.unsplash.com/photo-1472214103451-9374bd1c798e?q=80&w=2070&auto=format&fit=crop',
        'https://images.unsplash.com/photo-1447752875215-b2761acb3c5d?q=80&w=2070&auto=format&fit=crop'
    ];

    function safeParse(value) {
        try {
            return JSON.parse(value);
        } catch (_err) {
            return null;
        }
    }

    function getDailyImage() {
        const now = new Date();
        const start = new Date(now.getFullYear(), 0, 0);
        const diff = now - start;
        const oneDay = 1000 * 60 * 60 * 24;
        const day = Math.floor(diff / oneDay);
        return DAILY_BACKGROUNDS[day % DAILY_BACKGROUNDS.length];
    }

    function normalizeSettings(raw) {
        const next = { ...DEFAULTS, ...(raw || {}) };
        if (!['daily', 'profile-photo', 'custom'].includes(next.mode)) {
            next.mode = DEFAULT_MODE;
        }
        if (!Array.isArray(next.profilePhotoPages)) {
            next.profilePhotoPages = [...DEFAULTS.profilePhotoPages];
        }
        next.customImage = typeof next.customImage === 'string' ? next.customImage : '';
        return next;
    }

    function getSettings() {
        const stored = safeParse(window.localStorage.getItem(STORAGE_KEY));
        return normalizeSettings(stored);
    }

    function saveSettings(next) {
        const merged = normalizeSettings({ ...getSettings(), ...(next || {}) });
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(merged));
        return merged;
    }

    function buildBackgroundValue(src) {
        if (!src) return "url('/static/nature-bg.png')";
        return `url("${src}")`;
    }

    function applyBackground(options = {}) {
        try {
            const settings = normalizeSettings(options.settings || getSettings());
            const page = options.page || ((document.body && document.body.dataset && document.body.dataset.page) || '');
            const profilePhotoUrl = options.profilePhotoUrl || '';

            let chosen = getDailyImage();
            if (settings.mode === 'custom' && settings.customImage) {
                chosen = settings.customImage;
            } else if (
                settings.mode === 'profile-photo' &&
                profilePhotoUrl &&
                settings.profilePhotoPages.includes(page)
            ) {
                chosen = profilePhotoUrl;
            }

            document.documentElement.style.setProperty('--daily-bg', buildBackgroundValue(getDailyImage()));
            document.documentElement.style.setProperty('--ag-bg-image', buildBackgroundValue(chosen));
            document.documentElement.style.setProperty('--ag-bg-overlay', profilePhotoUrl && chosen === profilePhotoUrl
                ? 'linear-gradient(180deg, rgba(2, 6, 23, 0.42), rgba(2, 6, 23, 0.76))'
                : 'linear-gradient(180deg, rgba(2, 6, 23, 0.24), rgba(2, 6, 23, 0.68))');
            if (document.body) {
                document.body.setAttribute('data-background-mode', settings.mode);
            }
            return chosen;
        } catch (err) {
            console.error('Background apply failed', err);
            return '';
        }
    }

    function readFileAsDataUrl(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result || ''));
            reader.onerror = () => reject(new Error('Failed to read image'));
            reader.readAsDataURL(file);
        });
    }

    async function saveCustomImage(file) {
        if (!file) throw new Error('No image selected');
        const dataUrl = await readFileAsDataUrl(file);
        saveSettings({ mode: 'custom', customImage: dataUrl });
        applyBackground();
        return dataUrl;
    }

    function clearCustomImage() {
        saveSettings({ customImage: '', mode: DEFAULT_MODE });
        applyBackground();
    }

    window.AntigravityBackground = {
        DAILY_BACKGROUNDS,
        getSettings,
        saveSettings,
        applyBackground,
        saveCustomImage,
        clearCustomImage,
        getDailyImage
    };

    document.addEventListener('DOMContentLoaded', () => {
        applyBackground();
    });
})();
