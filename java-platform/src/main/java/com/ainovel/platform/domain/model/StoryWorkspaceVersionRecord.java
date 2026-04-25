package com.ainovel.platform.domain.model;

import java.time.Instant;

public record StoryWorkspaceVersionRecord(
        String versionId,
        String storyId,
        String nodeId,
        String label,
        String content,
        String source,
        Instant createdAt
) {}
