package com.ainovel.platform.domain.model;

import java.time.Instant;

public record RunRecord(
        String runId,
        String storyId,
        String status,
        Instant createdAt,
        Instant updatedAt
) {}
