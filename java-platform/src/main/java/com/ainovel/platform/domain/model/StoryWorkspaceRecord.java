package com.ainovel.platform.domain.model;

import java.time.Instant;
import java.util.List;
import java.util.Map;

public record StoryWorkspaceRecord(
        String storyId,
        String title,
        String premise,
        String style,
        Instant updatedAt,
        String activeNodeId,
        String activeRunId,
        Integer runAfterSeq,
        String runSyncStatus,
        Instant runSyncUpdatedAt,
        List<StoryWorkspaceNodeRecord> nodes,
        Map<String, String> contentByNodeId,
        List<StoryWorkspaceMessageRecord> assistantThread,
        Map<String, List<StoryWorkspaceBeatRecord>> beatByNodeId,
        List<StoryWorkspaceIssueRecord> consistencyIssues,
        Map<String, List<StoryWorkspaceVersionRecord>> versionsByNodeId
) {}
