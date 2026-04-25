package com.ainovel.platform.interfaces.dto;

import jakarta.validation.constraints.NotBlank;

import java.util.List;

public record CreateStoryRequest(
        @NotBlank String storyId,
        @NotBlank String runId,
        @NotBlank String title,
        @NotBlank String premise,
        String genre,
        String style,
        List<StoryCharacterRequest> characters,
        StoryWordCountRequest wordCount,
        @NotBlank String prompt,
        String provider,
        String model,
        String outputPath,
        String configPath
) {}
