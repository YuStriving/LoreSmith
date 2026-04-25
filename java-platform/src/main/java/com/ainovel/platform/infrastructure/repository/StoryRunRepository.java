package com.ainovel.platform.infrastructure.repository;

import com.ainovel.platform.domain.model.RunRecord;
import com.ainovel.platform.domain.model.StoryRecord;

import java.util.List;
import java.util.Optional;

public interface StoryRunRepository {
    StoryRecord saveStory(StoryRecord story);
    RunRecord saveRun(RunRecord run);
    Optional<StoryRecord> findStory(String storyId);
    Optional<RunRecord> findRun(String runId);
    List<StoryRecord> listStories();
    void deleteRunsByStoryId(String storyId);
    boolean deleteStoryById(String storyId);
}
