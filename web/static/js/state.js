(function initializeEdgeIQState(global) {
  global.EdgeIQState = {
    entryProps: [],
    recommendationOrigin: false,
    recommendationSnapshotId: "",
    entry: {
      review: {
        analysisRequestId: 0,
        lastAnalysis: null,
        lastEntryPayload: null,
        placementInFlight: false,
        invalidate() {
          this.analysisRequestId += 1;
          this.lastAnalysis = null;
          this.lastEntryPayload = null;
          return this.analysisRequestId;
        },
        beginPlacement() {
          if (this.placementInFlight || !this.lastEntryPayload) return false;
          this.placementInFlight = true;
          return true;
        },
        endPlacement() {
          this.placementInFlight = false;
        },
      },
      playerDirectory: [],
      selectedPlayerIdentityId: null,
      selectedPlayerRecord: null,
      directoryRequestId: 0,
      invalidatePlayerLookup() {
        this.directoryRequestId += 1;
        return this.directoryRequestId;
      },
      acceptPlayerLookup(requestId, players) {
        if (requestId !== this.directoryRequestId) return false;
        this.playerDirectory = Array.isArray(players) ? players : [];
        return true;
      },
      clearPlayerSelection() {
        this.selectedPlayerIdentityId = null;
        this.selectedPlayerRecord = null;
      },
    },
    commandCards: [],
    dailyBriefing: null,
    market: {
      opportunitySelections: new Set(),
      compareSelections: new Set(),
      compareTrackRecords: new Map(),
      trendingProps: [],
      trendingSelections: new Set(),
      trendingLoadId: 0,
      generatorRecentProps: {},
      boardEvidence: null,
      resetBriefingSelections() {
        this.opportunitySelections.clear();
        this.compareSelections.clear();
      },
      beginTrendingLoad() {
        this.trendingLoadId += 1;
        this.trendingSelections.clear();
        return this.trendingLoadId;
      },
      acceptTrendingLoad(requestId, props) {
        if (requestId !== this.trendingLoadId) return false;
        this.trendingProps = Array.isArray(props) ? props : [];
        return true;
      },
    },
    dailyScanPoll: null,
    dailyScanAutoStartedFor: "",
    deferredInstallPrompt: null,
    backgroundLoadPromise: null,
    deferredSignalsScheduled: false,
    ledgerLoadScheduled: false,
    loadedViews: new Set(),
    loadedWorkspacePanes: new Set(),
    buttonSoundsBound: false,
  };
})(window);
