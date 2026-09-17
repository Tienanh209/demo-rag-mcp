/* Vanilla-JS port of the `page-mascot` React component (MIT, Kamran Ahmed —
   https://github.com/nilbuild/page-mascot). This project has no bundler and no
   React, so the component's logic is reproduced directly rather than pulled in
   as an npm dependency; the sprite sheets in mascots/ are the package's own
   pre-drawn "knight" character, downloaded as-is.

   A character is two 3x3 sprite sheets — nine head directions, nine
   expressions. The pointer's angle picks a direction cell, with a dead zone so
   the head settles when the cursor is close, and hysteresis so it doesn't
   flicker between two cells at a sector boundary. A click ("boop") shows a
   reaction cell for half a second and plays a squash animation. One
   background-position swap per frame, no animation library. */

const DIRECTIONS = [
  'up-left', 'up', 'up-right',
  'left', 'center', 'right',
  'down-left', 'down', 'down-right',
];
const REACTIONS = [
  'blink', 'heart', 'sparkle',
  'surprised', 'wink', 'bashful',
  'sleepy', 'dizzy', 'delighted',
];
// Clockwise from the right, matching atan2 with y pointing down.
const CLOCKWISE = ['right', 'down-right', 'down', 'down-left', 'left', 'up-left', 'up', 'up-right'];
const SECTOR = (Math.PI * 2) / CLOCKWISE.length;
const HYSTERESIS = 0.12;
const DEAD_ZONE = 70;
const PAYOFFS = ['heart', 'sparkle', 'delighted'];
const BOOP_PAYOFF = 120;
const BOOP_END = 560;
const SQUASH_MS = 420;
const DIZZY_AFTER = 4;
const DIZZY_WINDOW = 1600;
const DIZZY_END = 1100;
const SQUASH = [
  { transform: 'scale(1, 1)', easing: 'ease-in' },
  { transform: 'scale(1.10, 0.86)', offset: 0.18, easing: 'ease-out' },
  { transform: 'scale(0.95, 1.08)', offset: 0.45, easing: 'ease-in-out' },
  { transform: 'scale(1.03, 0.97)', offset: 0.72, easing: 'ease-in-out' },
  { transform: 'scale(1, 1)' },
];

// background-size 300% makes each cell a clean 0/50/100% step on both axes.
function cellPosition(index) {
  return `${(index % 3) * 50}% ${Math.floor(index / 3) * 50}%`;
}
function wrap(angle) {
  return Math.atan2(Math.sin(angle), Math.cos(angle));
}

/* Mounts a mascot into `container` and wires up its own listeners. Returns an
   unmount function; also self-disconnects the window-level listeners the
   moment the button leaves the document, so a caller that just discards the
   old hero (as this app's showWelcome() does) can't leak them. */
export function mountMascot(container, opts = {}) {
  const { directions, reactions, size = 140, label = 'mascot', className = '' } = opts;

  const button = document.createElement('button');
  button.type = 'button';
  button.className = className;
  button.setAttribute('aria-label', `Boop the ${label}`);
  Object.assign(button.style, {
    position: 'relative', display: 'block', flexShrink: '0',
    width: `${size}px`, height: `${size}px`, padding: '0', border: '0',
    background: 'transparent', appearance: 'none', cursor: 'pointer', userSelect: 'none',
  });

  const squash = document.createElement('span');
  Object.assign(squash.style, {
    position: 'relative', display: 'block', width: '100%', height: '100%', transformOrigin: '50% 78%',
  });

  const layerStyle = { position: 'absolute', inset: '0', backgroundSize: '300% 300%', backgroundRepeat: 'no-repeat' };

  const dirLayer = document.createElement('span');
  Object.assign(dirLayer.style, layerStyle, { backgroundImage: `url(${directions})`, backgroundPosition: cellPosition(DIRECTIONS.indexOf('center')), opacity: '1' });

  const reactLayer = document.createElement('span');
  Object.assign(reactLayer.style, layerStyle, { backgroundImage: `url(${reactions})`, backgroundPosition: cellPosition(REACTIONS.indexOf('blink')), opacity: '0' });

  squash.append(dirLayer, reactLayer);
  button.append(squash);
  container.append(button);

  const setDirection = (name) => { dirLayer.style.backgroundPosition = cellPosition(DIRECTIONS.indexOf(name)); };
  const setReaction = (name) => {
    reactLayer.style.backgroundPosition = cellPosition(REACTIONS.indexOf(name ?? 'blink'));
    reactLayer.style.opacity = name ? '1' : '0';
    dirLayer.style.opacity = name ? '0' : '1';
  };

  // ── pointer tracking ────────────────────────────────────────────────────
  if (window.matchMedia('(hover: hover) and (pointer: fine)').matches) {
    let sector = -1;
    let pointer = null;

    const aim = () => {
      if (!button.isConnected) {
        window.removeEventListener('pointermove', onPointerMove);
        window.removeEventListener('scroll', aim);
        return;
      }
      if (!pointer) return;
      const box = button.getBoundingClientRect();
      const dx = pointer.x - (box.left + box.width / 2);
      const dy = pointer.y - (box.top + box.height / 2);
      if (Math.hypot(dx, dy) < DEAD_ZONE) {
        sector = -1;
        setDirection('center');
        return;
      }
      // Hold the current sector until the pointer is well past its edge.
      const angle = Math.atan2(dy, dx);
      if (sector !== -1 && Math.abs(wrap(angle - sector * SECTOR)) < SECTOR / 2 + HYSTERESIS) return;
      sector = (Math.round(angle / SECTOR) + CLOCKWISE.length) % CLOCKWISE.length;
      setDirection(CLOCKWISE[sector]);
    };
    const onPointerMove = (e) => { pointer = { x: e.clientX, y: e.clientY }; aim(); };
    window.addEventListener('pointermove', onPointerMove, { passive: true });
    window.addEventListener('scroll', aim, { passive: true });
  }

  // ── boop ────────────────────────────────────────────────────────────────
  let timers = [];
  const boops = { count: 0, at: 0 };
  const later = (ms, next) => { timers.push(window.setTimeout(() => setReaction(next), ms)); };

  button.addEventListener('click', () => {
    timers.forEach(window.clearTimeout);
    timers = [];
    const now = Date.now();
    boops.count = now - boops.at < DIZZY_WINDOW ? boops.count + 1 : 1;
    boops.at = now;

    if (boops.count >= DIZZY_AFTER) {
      boops.count = 0;
      setReaction('dizzy');
      later(DIZZY_END, null);
    } else {
      setReaction('blink');
      later(BOOP_PAYOFF, PAYOFFS[(boops.count - 1) % PAYOFFS.length]);
      later(BOOP_END, null);
    }

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    // Per-keyframe easing with the effect itself linear: an easing on the
    // effect would reinterpret every offset and front-load the whole bounce.
    squash.animate(SQUASH, { duration: SQUASH_MS, easing: 'linear' });
  });

  return () => { timers.forEach(window.clearTimeout); button.remove(); };
}
