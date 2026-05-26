import { useEffect } from 'react';

export default function useKeyboardShortcuts({
  onNewAppointment,
  onFocusSearch,
  onExport,
  onImport,
  onPrint,
}) {
  useEffect(() => {
    const handler = (e) => {
      // Only handle when no input/textarea is focused (unless it's a global shortcut)
      const tag = document.activeElement?.tagName?.toLowerCase();
      const isTyping = tag === 'input' || tag === 'textarea';

      if (e.metaKey || e.ctrlKey) {
        switch (e.key.toLowerCase()) {
          case 'n':
            e.preventDefault();
            onNewAppointment?.();
            break;
          case 'e':
            if (e.shiftKey) {
              e.preventDefault();
              onExport?.();
            }
            break;
          case 'i':
            if (e.shiftKey) {
              e.preventDefault();
              onImport?.();
            }
            break;
          case 'p':
            e.preventDefault();
            onPrint?.();
            break;
          case 'k':
            if (!isTyping) {
              e.preventDefault();
              onFocusSearch?.();
            }
            break;
          default:
            break;
        }
      }
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onNewAppointment, onFocusSearch, onExport, onImport, onPrint]);
}
