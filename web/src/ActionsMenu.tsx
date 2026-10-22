import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react';

/** One menu entry: either an action, or a flyout of further entries. `checked` shows a ✓. */
export interface MenuItem {
  label: string;
  onSelect?: () => void;
  checked?: boolean;
  items?: MenuItem[];
}

/** The entries of one menu level (not those of its flyouts). */
const entriesOf = (menu: Element) => Array.from(menu.querySelectorAll<HTMLElement>(':scope > li > [role^="menuitem"]'));

/** Arrow keys move between a menu level's entries, wrapping at either end. */
function moveFocus(e: KeyboardEvent<HTMLUListElement>) {
  const entries = entriesOf(e.currentTarget);
  const at = entries.indexOf(document.activeElement as HTMLElement);
  const step = e.key === 'ArrowDown' ? 1 : e.key === 'ArrowUp' ? -1 : 0;
  if (e.key === 'Home') entries[0]?.focus({ preventScroll: true });
  else if (e.key === 'End') entries[entries.length - 1]?.focus({ preventScroll: true });
  else if (step) entries[(at + step + entries.length) % entries.length]?.focus({ preventScroll: true });
  else return false;
  e.preventDefault();
  return true;
}

// Opening a menu announces it, so whichever other menu is open closes: only one is ever open.
const OPENED = 'actions-menu-opened';

const itemClass = 'flex w-full items-center gap-2 px-3 py-1.5 text-left text-[14px] text-navy hover:bg-[#eef1f5]';

/** A row's ⋯ (actions) button and the menu it opens, with side flyouts. */
export default function ActionsMenu({ label, items }: { label: string; items: MenuItem[] }) {
  const [open, setOpen] = useState(false);
  const [flyout, setFlyout] = useState<string | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLUListElement>(null);
  const flyoutMenu = useRef<HTMLUListElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const id = useId();
  const [flyoutSide, setFlyoutSide] = useState<'right' | 'left'>('right');
  // The menu is fixed to the window, under the trigger, so the table's scroll box doesn't clip it.
  const [place, setPlace] = useState<{ top: number; right: number }>({ top: 0, right: 0 });
  // A menu opened by hovering doesn't take focus and closes when the pointer leaves; a click pins it open.
  const byHover = useRef(false);
  const focusFlyout = useRef(false);
  const leaveTimer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => () => clearTimeout(leaveTimer.current), []);

  useEffect(() => {
    if (!open) return;
    window.dispatchEvent(new CustomEvent(OPENED, { detail: id }));
    const onOther = (e: Event) => {
      if ((e as CustomEvent).detail !== id) dismiss();
    };
    const onPointer = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) dismiss();
    };
    window.addEventListener(OPENED, onOther);
    document.addEventListener('mousedown', onPointer);
    // A fixed menu would drift from its row, so scrolling or resizing closes it.
    window.addEventListener('scroll', dismiss, true);
    window.addEventListener('resize', dismiss);
    return () => {
      window.removeEventListener(OPENED, onOther);
      document.removeEventListener('mousedown', onPointer);
      window.removeEventListener('scroll', dismiss, true);
      window.removeEventListener('resize', dismiss);
    };
  }, [open, id]);

  // A flyout that would run off the right edge of the window opens to the left instead.
  useLayoutEffect(() => {
    if (!flyout || !flyoutMenu.current) return;
    if (flyoutSide === 'right' && flyoutMenu.current.getBoundingClientRect().right > window.innerWidth) setFlyoutSide('left');
  }, [flyout, flyoutSide]);

  // Opening a menu or a flyout puts focus on its first entry.
  useEffect(() => {
    if (open && !byHover.current && menu.current) entriesOf(menu.current)[0]?.focus({ preventScroll: true });
  }, [open]);
  useEffect(() => {
    if (flyout && focusFlyout.current && flyoutMenu.current) entriesOf(flyoutMenu.current)[0]?.focus({ preventScroll: true });
  }, [flyout]);

  /** Closes without moving focus (focus has gone elsewhere already). */
  const dismiss = () => {
    clearTimeout(leaveTimer.current);
    setOpen(false);
    setFlyout(null);
    setFlyoutSide('right');
  };

  const close = () => {
    dismiss();
    trigger.current?.focus();
  };

  const openMenu = (viaHover = false) => {
    const rect = trigger.current?.getBoundingClientRect();
    if (rect) setPlace({ top: rect.bottom + 4, right: window.innerWidth - rect.right });
    byHover.current = viaHover;
    setOpen(true);
  };

  const openFlyout = (label: string, takeFocus: boolean) => {
    focusFlyout.current = takeFocus;
    setFlyout(label);
  };

  const onTriggerClick = () => {
    if (!open) openMenu();
    else if (byHover.current) byHover.current = false;
    else close();
  };

  const onEnter = () => {
    clearTimeout(leaveTimer.current);
    if (!open) openMenu(true);
  };

  const onLeave = () => {
    if (open && byHover.current) leaveTimer.current = setTimeout(dismiss, 250);
  };

  // Hovering an entry with a flyout opens it; hovering a plain top-level entry closes any open flyout.
  const onItemHover = (item: MenuItem, inFlyout: boolean) => {
    if (inFlyout) return;
    if (item.items) {
      if (flyout !== item.label) openFlyout(item.label, false);
    } else if (flyout) {
      setFlyout(null);
      setFlyoutSide('right');
    }
  };

  const closeFlyout = () => {
    const parent = menu.current && entriesOf(menu.current).find((el) => el.getAttribute('aria-expanded') === 'true');
    setFlyout(null);
    setFlyoutSide('right');
    parent?.focus();
  };

  const choose = (item: MenuItem) => {
    if (item.items) {
      if (flyout !== item.label) openFlyout(item.label, true);
      else if (!focusFlyout.current && flyoutMenu.current) {
        // Hovering opened it already; the click keeps it open and moves into it.
        focusFlyout.current = true;
        entriesOf(flyoutMenu.current)[0]?.focus({ preventScroll: true });
      } else closeFlyout();
      return;
    }
    close();
    item.onSelect?.();
  };

  const onMenuKey = (e: KeyboardEvent<HTMLUListElement>) => {
    if (moveFocus(e)) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
    } else if (e.key === 'ArrowRight') {
      const item = items.find((i) => i.label === (document.activeElement as HTMLElement).dataset.label);
      if (item?.items) {
        e.preventDefault();
        openFlyout(item.label, true);
      }
    } else if (e.key === 'Tab') {
      dismiss();
    }
  };

  const onFlyoutKey = (e: KeyboardEvent<HTMLUListElement>) => {
    e.stopPropagation();
    if (moveFocus(e)) return;
    if (e.key === 'Escape' || e.key === 'ArrowLeft') {
      e.preventDefault();
      closeFlyout();
    } else if (e.key === 'Tab') {
      dismiss();
    }
  };

  const entry = (item: MenuItem, inFlyout: boolean) => {
    const checkable = inFlyout && item.checked !== undefined;
    return (
      <li key={item.label} role="none" className="relative">
        <button
          type="button"
          role={checkable ? 'menuitemcheckbox' : 'menuitem'}
          aria-checked={checkable ? item.checked : undefined}
          aria-haspopup={item.items ? 'menu' : undefined}
          aria-expanded={item.items ? flyout === item.label : undefined}
          data-label={item.label}
          tabIndex={-1}
          onClick={() => choose(item)}
          onMouseEnter={() => onItemHover(item, inFlyout)}
          className={itemClass}
        >
          {inFlyout && (
            <span aria-hidden="true" className="w-3">
              {item.checked ? '✓' : ''}
            </span>
          )}
          <span className="flex-1">{item.label}</span>
          {item.items && <span aria-hidden="true">▸</span>}
        </button>
        {item.items && flyout === item.label && (
          <ul
            ref={flyoutMenu}
            role="menu"
            aria-label={item.label}
            data-side={flyoutSide}
            onKeyDown={onFlyoutKey}
            className={`absolute top-0 z-30 ${flyoutSide === 'right' ? 'left-full ml-1' : 'right-full mr-1'} min-w-[10rem] rounded-card border border-line bg-white py-1 shadow-lg`}
          >
            {item.items.map((sub) => entry(sub, true))}
          </ul>
        )}
      </li>
    );
  };

  return (
    <div ref={root} onMouseLeave={onLeave} onMouseEnter={() => clearTimeout(leaveTimer.current)} className="relative inline-block">
      <button
        ref={trigger}
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={onTriggerClick}
        onMouseEnter={onEnter}
        className="flex h-7 w-7 items-center justify-center rounded-full text-navy hover:bg-[#eef1f5] aria-expanded:bg-[#eef1f5]"
      >
        <svg aria-hidden="true" viewBox="0 0 16 16" className="h-4 w-4" fill="currentColor">
          <circle cx="3" cy="8" r="1.5" />
          <circle cx="8" cy="8" r="1.5" />
          <circle cx="13" cy="8" r="1.5" />
        </svg>
      </button>
      {open && (
        <ul ref={menu} role="menu" aria-label={label} onKeyDown={onMenuKey} style={place} className="fixed z-20 min-w-[12rem] rounded-card border border-line bg-white py-1 shadow-lg">
          {items.map((item) => entry(item, false))}
        </ul>
      )}
    </div>
  );
}
