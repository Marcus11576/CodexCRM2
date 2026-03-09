/**
 * Antigravity CRM — Global Background Manager
 * Handles dynamic Unsplash backdrops with a 'Platinum' curated selection.
 */
document.addEventListener('DOMContentLoaded', () => {
    const landscapes = [
        'https://images.unsplash.com/photo-1451187580459-43490279c0fa?q=80&w=2072&auto=format&fit=crop', // Blue Space/Earth
        'https://images.unsplash.com/photo-1446776811953-b23d57bd21aa?q=80&w=2072&auto=format&fit=crop', // Satellite Orbit
        'https://images.unsplash.com/photo-1464802686167-b939a6910659?q=80&w=2070&auto=format&fit=crop', // Deep Space Galaxy
        'https://images.unsplash.com/photo-1506744038136-46273834b3fb?q=80&w=2070&auto=format&fit=crop', // Yosemite Valley
        'https://images.unsplash.com/photo-1470071459604-3b5ec3a7fe05?q=80&w=2074&auto=format&fit=crop', // Foggy Forest
        'https://images.unsplash.com/photo-1441974231531-c6227db76b6e?q=80&w=2071&auto=format&fit=crop', // Sunlit Woods
        'https://images.unsplash.com/photo-1501785888041-af3ef285b470?q=80&w=2070&auto=format&fit=crop', // Lake Como
        'https://images.unsplash.com/photo-1493246507139-91e8bef99c02?q=80&w=2070&auto=format&fit=crop', // Mountain Peaks
        'https://images.unsplash.com/photo-1472214103451-9374bd1c798e?q=80&w=2070&auto=format&fit=crop', // Green Valley
        'https://images.unsplash.com/photo-1447752875215-b2761acb3c5d?q=80&w=2070&auto=format&fit=crop'  // Forest Path
    ];

    // Select image based on day of year for consistency
    const now = new Date();
    const start = new Date(now.getFullYear(), 0, 0);
    const diff = now - start;
    const oneDay = 1000 * 60 * 60 * 24;
    const day = Math.floor(diff / oneDay);
    
    const dailyImg = landscapes[day % landscapes.length];
    
    // Apply to CSS variable
    document.documentElement.style.setProperty('--daily-bg', `url('${dailyImg}')`);
    
    console.log('PLATINUM: Background updated to', dailyImg);
});
