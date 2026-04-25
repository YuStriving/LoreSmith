package com.ainovel.platform.domain.model;

import java.time.Instant;
import java.util.List;
import java.util.Map;

public record StoryRecord(
        String storyId,
        String title,
        String premise,
        String genre,
        String style,
        List<Map<String, Object>> characters,
        Map<String, Object> wordCount,
        Instant createdAt,
        String latestRunId
) {}
