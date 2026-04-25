package com.ainovel.platform.interfaces.dto;

import java.util.List;
import java.util.Map;

public record StoryResponse(
        String storyId,
        String title,
        String premise,
        String genre,
        String style,
        List<Map<String, Object>> characters,
        Map<String, Object> wordCount,
        String latestRunId,
        String createdAt
) {}
