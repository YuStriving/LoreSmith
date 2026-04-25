package com.ainovel.platform.infrastructure.repository;

import com.ainovel.platform.domain.model.RunRecord;
import com.ainovel.platform.domain.model.StoryRecord;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.Timestamp;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@Repository
public class JdbcStoryRunRepository implements StoryRunRepository {
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private static final TypeReference<List<Map<String, Object>>> LIST_OF_MAPS = new TypeReference<>() {};
    private static final TypeReference<Map<String, Object>> MAP_OF_OBJECTS = new TypeReference<>() {};

    private final JdbcTemplate jdbcTemplate;

    public JdbcStoryRunRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    @Override
    public StoryRecord saveStory(StoryRecord story) {
        jdbcTemplate.update("""
                INSERT INTO story_project (story_id, title, premise, genre_code, style_code, characters_json, word_count_json, latest_run_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, CAST(? AS jsonb), CAST(? AS jsonb), ?, ?, ?)
                ON CONFLICT (story_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    premise = EXCLUDED.premise,
                    genre_code = EXCLUDED.genre_code,
                    style_code = EXCLUDED.style_code,
                    characters_json = EXCLUDED.characters_json,
                    word_count_json = EXCLUDED.word_count_json,
                    latest_run_id = EXCLUDED.latest_run_id,
                    updated_at = EXCLUDED.updated_at
                """,
                story.storyId(),
                story.title(),
                story.premise(),
                story.genre(),
                story.style(),
                toJson(story.characters()),
                toJson(story.wordCount()),
                story.latestRunId(),
                Timestamp.from(story.createdAt()),
                Timestamp.from(story.createdAt())
        );
        return story;
    }

    @Override
    public RunRecord saveRun(RunRecord run) {
        jdbcTemplate.update("""
                INSERT INTO story_run (run_id, story_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (run_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at
                """,
                run.runId(),
                run.storyId(),
                run.status(),
                Timestamp.from(run.createdAt()),
                Timestamp.from(run.updatedAt())
        );
        return run;
    }

    @Override
    public Optional<StoryRecord> findStory(String storyId) {
        List<StoryRecord> rows = jdbcTemplate.query(
                "SELECT story_id, title, premise, genre_code, style_code, characters_json::text AS characters_json, word_count_json::text AS word_count_json, latest_run_id, created_at FROM story_project WHERE story_id = ?",
                (rs, rowNum) -> new StoryRecord(
                        rs.getString("story_id"),
                        rs.getString("title"),
                        rs.getString("premise"),
                        rs.getString("genre_code"),
                        rs.getString("style_code"),
                        fromJsonList(rs.getString("characters_json")),
                        fromJsonMap(rs.getString("word_count_json")),
                        rs.getTimestamp("created_at").toInstant(),
                        rs.getString("latest_run_id")
                ),
                storyId
        );
        return rows.stream().findFirst();
    }

    @Override
    public Optional<RunRecord> findRun(String runId) {
        List<RunRecord> rows = jdbcTemplate.query(
                "SELECT run_id, story_id, status, created_at, updated_at FROM story_run WHERE run_id = ?",
                (rs, rowNum) -> new RunRecord(
                        rs.getString("run_id"),
                        rs.getString("story_id"),
                        rs.getString("status"),
                        rs.getTimestamp("created_at").toInstant(),
                        rs.getTimestamp("updated_at").toInstant()
                ),
                runId
        );
        return rows.stream().findFirst();
    }

    @Override
    public List<StoryRecord> listStories() {
        return jdbcTemplate.query(
                "SELECT story_id, title, premise, genre_code, style_code, characters_json::text AS characters_json, word_count_json::text AS word_count_json, latest_run_id, created_at FROM story_project ORDER BY created_at ASC",
                (rs, rowNum) -> new StoryRecord(
                        rs.getString("story_id"),
                        rs.getString("title"),
                        rs.getString("premise"),
                        rs.getString("genre_code"),
                        rs.getString("style_code"),
                        fromJsonList(rs.getString("characters_json")),
                        fromJsonMap(rs.getString("word_count_json")),
                        rs.getTimestamp("created_at").toInstant(),
                        rs.getString("latest_run_id")
                )
        );
    }

    @Override
    public void deleteRunsByStoryId(String storyId) {
        jdbcTemplate.update("DELETE FROM story_run WHERE story_id = ?", storyId);
    }

    @Override
    public boolean deleteStoryById(String storyId) {
        return jdbcTemplate.update("DELETE FROM story_project WHERE story_id = ?", storyId) > 0;
    }

    private String toJson(Object value) {
        try {
            return OBJECT_MAPPER.writeValueAsString(value == null ? Map.of() : value);
        } catch (Exception ex) {
            throw new IllegalStateException("failed to serialize story metadata", ex);
        }
    }

    private List<Map<String, Object>> fromJsonList(String raw) {
        try {
            if (raw == null || raw.isBlank()) {
                return List.of();
            }
            return OBJECT_MAPPER.readValue(raw, LIST_OF_MAPS);
        } catch (Exception ex) {
            return List.of();
        }
    }

    private Map<String, Object> fromJsonMap(String raw) {
        try {
            if (raw == null || raw.isBlank()) {
                return Map.of();
            }
            return OBJECT_MAPPER.readValue(raw, MAP_OF_OBJECTS);
        } catch (Exception ex) {
            return new LinkedHashMap<>();
        }
    }
}
