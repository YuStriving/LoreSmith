package com.ainovel.platform.domain.model;

import java.time.Instant;

public record StoryWorkspaceBeatRecord(
        String beatId,
        String storyId,
        String nodeId,
        String title,
        String goal,
        String conflict,
        String outcome,
        Integer displayOrder,
        String status,
        Instant createdAt,
        Instant updatedAt
) {}
