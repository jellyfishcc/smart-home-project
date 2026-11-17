/* FAN/LAMP requests use explicit targets. Never infer a toggle from UI state. */
(function (root) {
    const pending = new Set();
    const revisions = new Map();
    root.EnvControls = {
        accept(device, state) {
            if (!['fan', 'light'].includes(device)) return true;
            const revision = Number(state.revision || 0);
            if (revision < (revisions.get(device) || 0)) return false;
            revisions.set(device, revision);
            return true;
        },
        reset() { revisions.clear(); },
        async run(device, request, onError) {
            if (pending.has(device)) return false;
            pending.add(device);
            const controls = Array.from(document.querySelectorAll(
                `[data-env-device="${device}"] input, [data-env-device="${device}"] button`));
            const previous = controls.map(control => control.disabled);
            controls.forEach(control => { control.disabled = true; });
            try {
                await request();
                return true;
            } catch (error) {
                onError(error);
                return false;
            } finally {
                controls.forEach((control, i) => { control.disabled = previous[i]; });
                pending.delete(device);
            }
        }
    };
})(globalThis);
