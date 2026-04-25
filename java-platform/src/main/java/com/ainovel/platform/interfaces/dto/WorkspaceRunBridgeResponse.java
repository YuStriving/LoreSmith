package com.ainovel.platform.interfaces.dto;

public record WorkspaceRunBridgeResponse(
        String activeRunId,
        Integer runAfterSeq,
        String runSyncStatus,
        String runSyncUpdatedAt,
        String lastCompletedChapter
) {}
