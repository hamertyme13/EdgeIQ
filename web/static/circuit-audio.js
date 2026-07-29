(function () {
  const STORAGE_KEY = "edgeiq.circuitAudio";
  let audioContext = null;

  function settings() {
    try {
      const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "{}");
      return {
        enabled: stored.enabled !== false,
        volume: Math.max(0, Math.min(1, Number(stored.volume ?? 0.42))),
      };
    } catch (error) {
      return { enabled: true, volume: 0.42 };
    }
  }

  function save(next) {
    const current = settings();
    const value = {
      enabled: next.enabled ?? current.enabled,
      volume: Math.max(0, Math.min(1, Number(next.volume ?? current.volume))),
    };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
    return value;
  }

  function context() {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return null;
    if (!audioContext) audioContext = new AudioContext();
    if (audioContext.state === "suspended") audioContext.resume().catch(() => {});
    return audioContext;
  }

  function tone(ctx, destination, options) {
    const start = ctx.currentTime + (options.delay || 0);
    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();
    oscillator.type = options.type || "sine";
    oscillator.frequency.setValueAtTime(options.frequency, start);
    oscillator.frequency.exponentialRampToValueAtTime(
      Math.max(20, options.endFrequency || options.frequency),
      start + options.duration
    );
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(options.gain || 0.12, start + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + options.duration);
    oscillator.connect(gain);
    gain.connect(destination);
    oscillator.start(start);
    oscillator.stop(start + options.duration + 0.02);
  }

  function spark(ctx, destination, delay = 0) {
    const duration = 0.085;
    const buffer = ctx.createBuffer(1, Math.ceil(ctx.sampleRate * duration), ctx.sampleRate);
    const channel = buffer.getChannelData(0);
    for (let index = 0; index < channel.length; index += 1) {
      channel[index] = (Math.random() * 2 - 1) * (1 - index / channel.length);
    }
    const source = ctx.createBufferSource();
    const filter = ctx.createBiquadFilter();
    const gain = ctx.createGain();
    const start = ctx.currentTime + delay;
    source.buffer = buffer;
    filter.type = "bandpass";
    filter.frequency.value = 2400;
    filter.Q.value = 4.2;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.1, start + 0.008);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
    source.connect(filter);
    filter.connect(gain);
    gain.connect(destination);
    source.start(start);
  }

  function play(kind = "engage", options = {}) {
    const current = settings();
    if (!current.enabled && !options.force) return false;
    const ctx = context();
    if (!ctx) return false;
    const master = ctx.createGain();
    master.gain.value = current.volume * 0.34;
    master.connect(ctx.destination);

    if (kind === "tap") {
      tone(ctx, master, {
        frequency: 460,
        endFrequency: 520,
        duration: 0.055,
        type: "sine",
        gain: 0.075,
      });
      return true;
    }

    if (kind === "navigate") {
      tone(ctx, master, {
        frequency: 260,
        endFrequency: 310,
        duration: 0.065,
        type: "triangle",
        gain: 0.075,
      });
      tone(ctx, master, {
        frequency: 410,
        endFrequency: 460,
        delay: 0.038,
        duration: 0.07,
        type: "sine",
        gain: 0.06,
      });
      return true;
    }

    if (kind === "select") {
      spark(ctx, master);
      tone(ctx, master, {
        frequency: 510,
        endFrequency: 720,
        duration: 0.1,
        type: "triangle",
        gain: 0.1,
      });
      return true;
    }

    if (kind === "scan") {
      tone(ctx, master, {
        frequency: 740,
        endFrequency: 1480,
        duration: 0.18,
        type: "sine",
        gain: 0.085,
      });
      tone(ctx, master, {
        frequency: 1080,
        endFrequency: 1680,
        delay: 0.075,
        duration: 0.16,
        type: "triangle",
        gain: 0.055,
      });
      return true;
    }

    if (kind === "inspect") {
      tone(ctx, master, {
        frequency: 330,
        endFrequency: 440,
        duration: 0.13,
        type: "sine",
        gain: 0.085,
      });
      tone(ctx, master, {
        frequency: 660,
        endFrequency: 640,
        delay: 0.045,
        duration: 0.11,
        type: "triangle",
        gain: 0.05,
      });
      return true;
    }

    if (kind === "delete") {
      tone(ctx, master, {
        frequency: 210,
        endFrequency: 105,
        duration: 0.15,
        type: "square",
        gain: 0.07,
      });
      return true;
    }

    if (kind === "success") {
      spark(ctx, master, 0.01);
      [[392, 0], [587.33, 0.075], [880, 0.15]].forEach(([frequency, delay], index) => tone(ctx, master, {
        frequency,
        endFrequency: frequency * 1.04,
        delay,
        duration: 0.22,
        type: index === 2 ? "sine" : "triangle",
        gain: index === 2 ? 0.18 : 0.14,
      }));
      return true;
    }

    if (kind === "warning") {
      tone(ctx, master, {
        frequency: 190,
        endFrequency: 118,
        duration: 0.24,
        type: "sawtooth",
        gain: 0.13,
      });
      tone(ctx, master, {
        frequency: 160,
        endFrequency: 105,
        delay: 0.11,
        duration: 0.25,
        type: "square",
        gain: 0.075,
      });
      return true;
    }

    spark(ctx, master);
    tone(ctx, master, {
      frequency: 760,
      endFrequency: 1280,
      duration: 0.12,
      type: "triangle",
      gain: 0.12,
    });
    tone(ctx, master, {
      frequency: 132,
      endFrequency: 82,
      duration: 0.18,
      type: "sine",
      gain: 0.16,
    });
    return true;
  }

  window.EdgeIQAudio = { play, save, settings };
})();
