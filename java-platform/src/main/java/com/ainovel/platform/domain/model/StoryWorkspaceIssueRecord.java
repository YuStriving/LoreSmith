package com.ainovel.platform.domain.model;

import java.time.Instant;

public record StoryWorkspaceIssueRecord(
        String issueId,
        String storyId,
        String nodeId,
        String severity,
        String category,
        String title,
        String description,
        String status,
        Instant createdAt,
        Instant updatedAt
) {}
