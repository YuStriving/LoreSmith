package com.ainovel.platform.domain.model;

import java.time.Instant;

public record StoryWorkspaceMessageRecord(
        String messageId,
        String storyId,
        String role,
        String content,
        Instant createdAt
) {}
