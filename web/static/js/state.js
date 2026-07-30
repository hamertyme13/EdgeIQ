(function initializeEdgeIQState(global) {
  global.EdgeIQState = {
    entryProps: [],
    lastEntryPayload: null,
    lastAnalysis: null,
    recommendationOrigin: false,
    commandCards: [],
    dailyBriefing: null,
    dailyScanPoll: null,
    dailyScanAutoStartedFor: "",
    deferredInstallPrompt: null,
    backgroundLoadPromise: null,
    deferredSignalsScheduled: false,
    ledgerLoadScheduled: false,
    loadedViews: new Set(),
    loadedWorkspacePanes: new Set(),
    placementInFlight: false,
    buttonSoundsBound: false,
  };
})(window);
