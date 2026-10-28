(() => {
  const canvas = document.getElementById("landing-particles");
  if (!canvas) return;

  const context = canvas.getContext("2d", { alpha: false });
  if (!context) return;

  const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
  const particles = [];
  const pointer = { x: -1000, y: -1000, active: false };
  let width = 0;
  let height = 0;
  let animationFrame = 0;
  let previousTime = 0;
  let pixelRatio = 1;

  function makeParticle(randomY = true) {
    return {
      x: Math.random() * width,
      y: randomY ? Math.random() * height : height + Math.random() * 24,
      drift: (Math.random() - 0.5) * 0.42,
      rise: 0.12 + Math.random() * 0.48,
      radius: 0.7 + Math.random() * 1.7,
      phase: Math.random() * Math.PI * 2,
      hue: 195 + Math.random() * 35,
    };
  }

  function resize() {
    const bounds = canvas.getBoundingClientRect();
    width = Math.max(1, bounds.width);
    height = Math.max(1, bounds.height);
    pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5);
    canvas.width = Math.round(width * pixelRatio);
    canvas.height = Math.round(height * pixelRatio);
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);

    const targetCount = Math.min(260, Math.max(70, Math.round((width * height) / 1700)));
    while (particles.length < targetCount) particles.push(makeParticle());
    particles.length = targetCount;
    paint(0, false);
  }

  function paint(time, advance) {
    context.fillStyle = "#0b1220";
    context.fillRect(0, 0, width, height);

    const glow = context.createRadialGradient(width * 0.5, height * 0.92, 0, width * 0.5, height * 0.92, height * 0.85);
    glow.addColorStop(0, "rgba(51, 101, 173, 0.24)");
    glow.addColorStop(1, "rgba(11, 18, 32, 0)");
    context.fillStyle = glow;
    context.fillRect(0, 0, width, height);

    for (let index = 0; index < particles.length; index += 1) {
      const particle = particles[index];
      if (advance) {
        particle.phase += 0.006;
        particle.x += particle.drift + Math.sin(particle.phase + time * 0.00025) * 0.2;
        particle.y -= particle.rise;

        if (pointer.active) {
          const dx = particle.x - pointer.x;
          const dy = particle.y - pointer.y;
          const distanceSquared = dx * dx + dy * dy;
          const radius = 110;
          if (distanceSquared < radius * radius && distanceSquared > 1) {
            const force = (1 - Math.sqrt(distanceSquared) / radius) * 1.1;
            particle.x += (dx / Math.sqrt(distanceSquared)) * force;
            particle.y += (dy / Math.sqrt(distanceSquared)) * force;
          }
        }

        if (particle.y < -8 || particle.x < -12 || particle.x > width + 12) {
          Object.assign(particle, makeParticle(false));
        }
      }

      const twinkle = 0.55 + Math.sin(particle.phase + time * 0.001) * 0.2;
      context.beginPath();
      context.arc(particle.x, particle.y, particle.radius, 0, Math.PI * 2);
      context.fillStyle = `hsla(${particle.hue}, 95%, 78%, ${twinkle})`;
      context.shadowColor = `hsla(${particle.hue}, 100%, 70%, 0.85)`;
      context.shadowBlur = particle.radius * 5;
      context.fill();
      context.shadowBlur = 0;

      for (let otherIndex = index + 1; otherIndex < particles.length; otherIndex += 1) {
        const other = particles[otherIndex];
        const dx = particle.x - other.x;
        const dy = particle.y - other.y;
        const distanceSquared = dx * dx + dy * dy;
        if (distanceSquared < 58 * 58) {
          context.beginPath();
          context.moveTo(particle.x, particle.y);
          context.lineTo(other.x, other.y);
          context.strokeStyle = `rgba(118, 180, 255, ${(1 - Math.sqrt(distanceSquared) / 58) * 0.13})`;
          context.lineWidth = 0.65;
          context.stroke();
        }
      }
    }
  }

  function animate(time) {
    animationFrame = 0;
    if (document.hidden) return;
    const elapsed = Math.min(time - (previousTime || time), 32);
    previousTime = time;
    paint(time, elapsed > 0);
    if (!motionPreference.matches) animationFrame = window.requestAnimationFrame(animate);
  }

  function start() {
    if (animationFrame || document.hidden || motionPreference.matches) return;
    previousTime = 0;
    animationFrame = window.requestAnimationFrame(animate);
  }

  function handleMotionPreference() {
    if (motionPreference.matches) {
      window.cancelAnimationFrame(animationFrame);
      animationFrame = 0;
      paint(0, false);
    } else {
      start();
    }
  }

  canvas.addEventListener("pointermove", (event) => {
    const bounds = canvas.getBoundingClientRect();
    pointer.x = event.clientX - bounds.left;
    pointer.y = event.clientY - bounds.top;
    pointer.active = true;
  }, { passive: true });
  canvas.addEventListener("pointerleave", () => { pointer.active = false; });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      window.cancelAnimationFrame(animationFrame);
      animationFrame = 0;
    } else {
      start();
    }
  });
  motionPreference.addEventListener?.("change", handleMotionPreference);
  new ResizeObserver(resize).observe(canvas);
  resize();
  start();
})();