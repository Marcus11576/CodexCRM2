/**
 * Antigravity CRM — Strategist Plugin (V2)
 * Displays deep relationship insights from the Strategist Service.
 */
const StrategistPlugin = {
    id: 'strategist-v2',
    mountPoint: 'profile-intelligence-v2',

    render: async (mountEl, context) => {
        const personId = context.person_id;
        if (!personId) return;

        mountEl.innerHTML = `
            <div class="card mt-4" style="border-image: linear-gradient(135deg, var(--accent-cyan), var(--accent-violet)) 1; border-width: 1px; border-style: solid; background: rgba(34,211,238,0.03);">
                <div class="card-header">
                    <h3 class="card-title" style="color: var(--accent-cyan);"><i class="fas fa-brain"></i> Platinum Strategic Synthesis</h3>
                    <button id="btn-run-synthesis" class="btn btn-sm btn-ghost" style="font-size: 0.65rem; border-color: var(--accent-cyan); color: var(--accent-cyan);">
                        <i class="fas fa-sync"></i> Refresh Synthesis
                    </button>
                </div>
                <div id="synthesis-content" class="p-2">
                    <div class="skeleton" style="height: 100px; width: 100%;"></div>
                </div>
            </div>
        `;

        const renderContent = (data) => {
            const content = document.getElementById('synthesis-content');
            if (!data || data.error) {
                content.innerHTML = `<p class="text-muted text-xs">Run synthesis to generate deep insights for ${context.full_name}.</p>`;
                return;
            }

            content.innerHTML = `
                <div class="flex flex-col gap-4">
                    <div class="glass-sm p-3">
                        <div class="text-xs font-bold text-accent mb-1 uppercase tracking-wider">Strategic SIT-REP</div>
                        <p class="text-sm opacity-90">${data.sitrep_brief}</p>
                    </div>
                    
                    <div class="grid-2">
                        <div class="p-2">
                            <div class="text-xs font-bold text-secondary mb-2 uppercase tracking-tight">Intelligence Gaps</div>
                            <ul class="text-xs list-disc pl-4 opacity-80">
                                ${data.intelligence_gaps.map(g => `<li class="mb-1">${g}</li>`).join('')}
                            </ul>
                        </div>
                        <div class="p-2">
                            <div class="text-xs font-bold text-secondary mb-2 uppercase tracking-tight">Hypotheses</div>
                            <ul class="text-xs list-disc pl-4 opacity-80">
                                ${data.strategic_hypotheses.map(h => `<li class="mb-1">${h}</li>`).join('')}
                            </ul>
                        </div>
                    </div>
                </div>
            `;
        };

        const runSynthesis = async () => {
            const btn = document.getElementById('btn-run-synthesis');
            btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Processing...';
            btn.disabled = true;

            try {
                const res = await fetch(`/api/v2/intelligence/synthesize/${person_id}`, { method: 'POST' });
                const data = await res.json();
                renderContent(data);
            } catch (err) {
                console.error(err);
                alert("Synthesis failed.");
            } finally {
                btn.innerHTML = '<i class="fas fa-sync"></i> Refresh Synthesis';
                btn.disabled = false;
            }
        };

        document.getElementById('btn-run-synthesis').onclick = runSynthesis;
        
        // Initial state
        renderContent(null);
    }
};

window.AntigravityPlugins.register(StrategistPlugin);
