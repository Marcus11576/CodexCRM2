/**
 * Antigravity CRM — Plugin Manager
 * Allows dynamic injection of V2 features into established pages.
 */
class PluginManager {
    constructor() {
        this.plugins = [];
    }

    /**
     * Registers a new plugin.
     * @param {Object} plugin - { id, mountPoint, render }
     */
    register(plugin) {
        console.log(`PLUGIN: Registering ${plugin.id}...`);
        this.plugins.push(plugin);
    }

    /**
     * Mounts all registered plugins to their respective points.
     * @param {string} containerId - The ID of the container where plugins should look for points.
     * @param {Object} context - Data context (e.g., person object)
     */
    mountAll(containerId, context) {
        const container = document.getElementById(containerId);
        if (!container) return;

        this.plugins.forEach(plugin => {
            let mountEl = document.querySelector(`[data-plugin-mount="${plugin.mountPoint}"]`);
            
            // If mount point doesn't exist, create it at the bottom of the container
            if (!mountEl) {
                mountEl = document.createElement('div');
                mountEl.setAttribute('data-plugin-mount', plugin.mountPoint);
                mountEl.className = 'plugin-mount-point';
                container.appendChild(mountEl);
            }

            try {
                plugin.render(mountEl, context);
            } catch (err) {
                console.error(`PLUGIN ERROR (${plugin.id}):`, err);
            }
        });
    }
}

window.AntigravityPlugins = new PluginManager();
