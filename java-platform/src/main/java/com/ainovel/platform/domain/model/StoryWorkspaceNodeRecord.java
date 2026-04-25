package com.ainovel.platform.domain.model;

import java.time.Instant;

public record StoryWorkspaceNodeRecord(
        String nodeId,
        String storyId,
        String parentId,
        String type,
        String title,
        Integer displayOrder,
        String summary,
        Instant createdAt,
        Instant updatedAt
) {}
