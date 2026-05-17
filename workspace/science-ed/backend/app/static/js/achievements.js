/**
 * achievements.js — Achievement badge display and toast notifications
 * for the ScienceEd student dashboard.
 *
 * Dependencies: none (vanilla JS, < 8KB)
 *
 * Usage:
 *   <script src="/static/js/achievements.js"></script>
 *   <script>
 *     ScienceEdAchievements.init({ apiBase: '/api/v1' });
 *   </script>
 *
 * HTML structure for the badge gallery:
 *   <div id="achievement-gallery" data-student-id="..."></div>
 *
 * Toast notifications auto-appear when the student returns to the
 * dashboard after unlocking a badge.
 */

(function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // Configuration
  // ---------------------------------------------------------------------------

  var defaults = {
    apiBase: '/api/v1',
    gallerySelector: '#achievement-gallery',
    toastContainer: '#achievement-toast-container',
    debug: false,
  };

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  var config = {};
  var badgeCache = null;  // Full catalog, loaded once

  // ---------------------------------------------------------------------------
  // Logging
  // ---------------------------------------------------------------------------

  function log() {
    if (config.debug && window.console) {
      console.log('[ScienceEd Achievements]', Array.prototype.slice.call(arguments));
    }
  }

  // ---------------------------------------------------------------------------
  // HTTP helpers
  // ---------------------------------------------------------------------------

  function getAuthHeaders() {
    var token = localStorage.getItem('science_ed_token');
    if (!token) return {};
    return { Authorization: 'Bearer ' + token };
  }

  function apiGet(path) {
    var url = config.apiBase + path;
    return fetch(url, {
      method: 'GET',
      headers: Object.assign({ Accept: 'application/json' }, getAuthHeaders()),
    }).then(function (r) {
      if (!r.ok) throw new Error('API error ' + r.status + ' on GET ' + path);
      return r.json();
    });
  }

  function apiPost(path) {
    var url = config.apiBase + path;
    return fetch(url, {
      method: 'POST',
      headers: Object.assign(
        { Accept: 'application/json', 'Content-Type': 'application/json' },
        getAuthHeaders()
      ),
    }).then(function (r) {
      if (!r.ok) throw new Error('API error ' + r.status + ' on POST ' + path);
      return r.json();
    });
  }

  // ---------------------------------------------------------------------------
  // Icon mapping
  // ---------------------------------------------------------------------------

  var ICON_MAP = {
    compass: '🧭',
    book: '📚',
    flask: '🔬',
    rocket: '🚀',
    fire: '🔥',
    crown: '👑',
    star: '⭐',
    target: '🎯',
    moon: '🌙',
    sun: '🌅',
  };

  function getIcon(iconName) {
    return ICON_MAP[iconName] || '🏆';
  }

  // ---------------------------------------------------------------------------
  // Badge Catalog (cached)
  // ---------------------------------------------------------------------------

  function loadCatalog() {
    if (badgeCache) return Promise.resolve(badgeCache);
    return apiGet('/achievements').then(function (data) {
      badgeCache = data.achievements || data || [];
      if (!Array.isArray(badgeCache)) badgeCache = [];
      return badgeCache;
    });
  }

  // ---------------------------------------------------------------------------
  // Toast notification system
  // ---------------------------------------------------------------------------

  function createToastContainer() {
    var el = document.querySelector(config.toastContainer);
    if (el) return el;
    el = document.createElement('div');
    el.id = 'achievement-toast-container';
    el.style.cssText =
      'position:fixed;bottom:20px;right:20px;z-index:9999;' +
      'display:flex;flex-direction:column-reverse;gap:10px;' +
      'pointer-events:none;';
    document.body.appendChild(el);
    return el;
  }

  function showToast(achievement) {
    var container = createToastContainer();
    var emoji = getIcon(achievement.icon_name || achievement.achievement.icon_name);
    var name = achievement.display_name_en || achievement.achievement.display_name_en || 'Achievement Unlocked!';
    var desc =
      achievement.description_en || achievement.achievement.description_en || '';

    var toast = document.createElement('div');
    toast.style.cssText =
      'background:linear-gradient(135deg,#4f46e5,#7c3aed);color:#fff;' +
      'padding:14px 20px;border-radius:12px;box-shadow:0 4px 24px rgba(79,70,229,0.4);' +
      'display:flex;align-items:center;gap:12px;font-family:sans-serif;' +
      'transform:translateX(120%);opacity:0;' +
      'transition:transform 0.4s cubic-bezier(0.34,1.56,0.64,1),opacity 0.3s ease;' +
      'max-width:360px;pointer-events:auto;cursor:pointer;';

    toast.innerHTML =
      '<div style="font-size:32px;line-height:1;">' +
      emoji +
      '</div>' +
      '<div>' +
      '<div style="font-weight:700;font-size:15px;margin-bottom:2px;">🏆 ' +
      name +
      '</div>' +
      '<div style="font-size:13px;opacity:0.9;">' +
      desc +
      '</div>' +
      '</div>';

    container.appendChild(toast);

    // Animate in
    requestAnimationFrame(function () {
      toast.style.transform = 'translateX(0)';
      toast.style.opacity = '1';
    });

    // Dismiss on click
    toast.addEventListener('click', function () {
      dismissToast(toast);
    });

    // Auto-dismiss after 6 seconds
    setTimeout(function () {
      dismissToast(toast);
    }, 6000);
  }

  function dismissToast(toast) {
    toast.style.transform = 'translateX(120%)';
    toast.style.opacity = '0';
    setTimeout(function () {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 400);
  }

  // ---------------------------------------------------------------------------
  // Check for pending notifications
  // ---------------------------------------------------------------------------

  function checkPendingNotifications() {
    apiGet('/achievements/notifications')
      .then(function (data) {
        var unlocks = data.unlocks || [];
        if (unlocks.length === 0) return;
        log('Pending notifications:', unlocks.length);
        unlocks.forEach(function (u) {
          showToast(u);
        });
        // Dismiss after showing
        return apiPost('/achievements/notifications/dismiss');
      })
      .catch(function (err) {
        log('Error checking notifications:', err);
      });
  }

  // ---------------------------------------------------------------------------
  // Gallery rendering
  // ---------------------------------------------------------------------------

  function renderAchievementGallery(studentAchievements, catalog) {
    var container = document.querySelector(config.gallerySelector);
    if (!container) {
      log('Gallery container not found:', config.gallerySelector);
      return;
    }

    // Build a map of code -> student record
    var unlocked = {};
    (studentAchievements || []).forEach(function (sa) {
      unlocked[sa.achievement.code] = sa;
    });

    var html =
      '<div class="achievement-grid" style="' +
      'display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));' +
      'gap:16px;padding:16px 0;">';

    (catalog || []).forEach(function (badge) {
      var isUnlocked = !!unlocked[badge.code];
      var emoji = getIcon(badge.icon_name);
      var unlockedDate = '';
      if (isUnlocked && unlocked[badge.code].unlocked_at) {
        var d = new Date(unlocked[badge.code].unlocked_at);
        unlockedDate = d.toLocaleDateString();
      }

      html +=
        '<div class="achievement-badge" ' +
        'style="' +
        'background:' +
        (isUnlocked
          ? 'linear-gradient(135deg,#4f46e5,#7c3aed)'
          : '#f3f4f6') +
        ';' +
        'border-radius:12px;padding:16px;text-align:center;' +
        (isUnlocked ? 'color:#fff;' : 'color:#9ca3af;') +
        'box-shadow:0 2px 8px rgba(0,0,0,0.08);' +
        'transition:transform 0.2s ease,box-shadow 0.2s ease;' +
        'cursor:default;' +
        '" title="' +
        badge.description_en +
        '">' +
        '<div style="font-size:36px;margin-bottom:8px;' +
        (isUnlocked ? '' : 'filter:grayscale(1);opacity:0.4;') +
        '">' +
        emoji +
        '</div>' +
        '<div style="font-weight:700;font-size:13px;line-height:1.3;' +
        (isUnlocked ? '' : '') +
        '">' +
        badge.display_name_en +
        '</div>' +
        (isUnlocked && unlockedDate
          ? '<div style="font-size:11px;margin-top:4px;opacity:0.8;">' +
            unlockedDate +
            '</div>'
          : '') +
        '</div>';
    });

    html += '</div>';
    container.innerHTML = html;
  }

  // ---------------------------------------------------------------------------
  // Streak display
  // ---------------------------------------------------------------------------

  function renderStreakInfo(streakInfo) {
    var container = document.querySelector(config.gallerySelector);
    if (!container) return;

    var current = streakInfo.current_streak || 0;

    var streakHtml =
      '<div class="streak-display" style="' +
      'display:flex;align-items:center;gap:12px;padding:16px;' +
      'background:linear-gradient(135deg,#f59e0b,#ef4444);border-radius:12px;' +
      'color:#fff;margin-bottom:20px;">' +
      '<div style="font-size:36px;">🔥</div>' +
      '<div>' +
      '<div style="font-weight:700;font-size:24px;">' +
      current +
      ' day' +
      (current !== 1 ? 's' : '') +
      '</div>' +
      '<div style="font-size:13px;opacity:0.9;">Learning streak</div>' +
      '</div>' +
      '</div>';

    // Prepend before the gallery
    var existing = container.querySelector('.streak-display');
    if (existing) {
      existing.outerHTML = streakHtml;
    } else {
      var wrapper = document.createElement('div');
      wrapper.innerHTML = streakHtml;
      container.insertBefore(wrapper.firstElementChild, container.firstChild);
    }
  }

  // ---------------------------------------------------------------------------
  // Main initialization
  // ---------------------------------------------------------------------------

  function init(userOptions) {
    config = Object.assign({}, defaults, userOptions || {});
    log('Initialized with config:', config);

    var gallery = document.querySelector(config.gallerySelector);
    if (gallery) {
      // Load catalog and student achievements in parallel
      Promise.all([loadCatalog(), apiGet('/achievements/student')])
        .then(function (results) {
          var catalog = results[0];
          var studentData = results[1];
          var studentAchievements = studentData.achievements || [];
          var streakInfo = studentData.streak || {};

          renderStreakInfo(streakInfo);
          renderAchievementGallery(studentAchievements, catalog);
        })
        .catch(function (err) {
          log('Error loading achievements:', err);
          gallery.innerHTML =
            '<p style="color:#6b7280;text-align:center;">Could not load achievements</p>';
        });
    }

    // Check for pending toast notifications
    checkPendingNotifications();
  }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  var ScienceEdAchievements = {
    init: init,
    checkNotifications: checkPendingNotifications,
    loadCatalog: loadCatalog,
    showToast: showToast,
  };

  // Export globally
  if (typeof window !== 'undefined') {
    window.ScienceEdAchievements = ScienceEdAchievements;
  }

  // Auto-init if the gallery element exists and data-autoload is set
  if (typeof document !== 'undefined') {
    var script = document.currentScript;
    if (script && script.hasAttribute('data-autoload')) {
      var attrs = {};
      ['apiBase', 'debug'].forEach(function (key) {
        if (script.hasAttribute('data-' + key)) {
          attrs[key] = script.getAttribute('data-' + key);
          if (key === 'debug') attrs[key] = attrs[key] === 'true';
        }
      });
      init(attrs);
    }
  }
})();
