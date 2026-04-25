package com.ainovel.platform.infrastructure.repository;

import com.ainovel.platform.domain.model.RunRecord;
import com.ainovel.platform.domain.model.StoryRecord;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

public class InMemoryStoryRunRepository implements StoryRunRepository {
    private final Map<String, StoryRecord> stories = new ConcurrentHashMap<>();
    private final Map<String, RunRecord> runs = new ConcurrentHashMap<>();

    public StoryRecord saveStory(StoryRecord story) {
        stories.put(story.storyId(), story);
        return story;
    }

    public RunRecord saveRun(RunRecord run) {
        runs.put(run.runId(), run);
        return run;
    }

    public Optional<StoryRecord> findStory(String storyId) {
        return Optional.ofNullable(stories.get(storyId));
    }

    public Optional<RunRecord> findRun(String runId) {
        return Optional.ofNullable(runs.get(runId));
    }

    public List<StoryRecord> listStories() {
        return List.copyOf(stories.values());
    }

    public void deleteRunsByStoryId(String storyId) {
        runs.entrySet().removeIf(entry -> storyId.equals(entry.getValue().storyId()));
    }

    public boolean deleteStoryById(String storyId) {
        return stories.remove(storyId) != null;
    }
}
