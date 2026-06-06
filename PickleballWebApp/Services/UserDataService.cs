using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using Microsoft.AspNetCore.Hosting;
using PickleballWebApp.Models;

namespace PickleballWebApp.Services
{
    public class UserDataService
    {
        private readonly string _dataRoot;
        private const int MaxVisitsStored = 100;

        private static readonly JsonSerializerOptions _json = new()
        {
            WriteIndented = true,
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase
        };

        public UserDataService(IWebHostEnvironment env)
        {
            _dataRoot = Path.Combine(env.ContentRootPath, "user-data");
            Directory.CreateDirectory(_dataRoot);
        }

        // ──────── SESSION MANAGEMENT ────────

        public void SaveSession(SessionResult session)
        {
            var dir = SessionDir(session.Username);
            Directory.CreateDirectory(dir);
            var path = Path.Combine(dir, session.Id + ".json");
            File.WriteAllText(path, JsonSerializer.Serialize(session, _json));
        }

        public List<SessionResult> GetSessions(string username, int limit = 50)
        {
            var dir = SessionDir(username);
            if (!Directory.Exists(dir)) return new List<SessionResult>();

            return Directory.GetFiles(dir, "*.json")
                .OrderByDescending(File.GetLastWriteTimeUtc)
                .Take(limit)
                .Select(f =>
                {
                    try { return JsonSerializer.Deserialize<SessionResult>(File.ReadAllText(f), _json); }
                    catch { return null; }
                })
                .Where(s => s != null)
                .ToList()!;
        }

        public UserStats GetStats(string username)
        {
            var sessions = GetSessions(username, 200);
            if (sessions.Count == 0)
                return new UserStats();

            var accuracies = sessions.Select(s => s.OverallAccuracy).ToList();
            return new UserStats
            {
                TotalSessions = sessions.Count,
                AverageAccuracy = Math.Round(accuracies.Average(), 1),
                BestAccuracy = Math.Round(accuracies.Max(), 1),
                LastSessionAt = sessions.Max(s => s.CreatedAt),
                RecentTrend = ComputeTrend(sessions)
            };
        }

        // ──────── PAGE VISIT TRACKING ────────

        public void RecordPageVisit(string username, string path, string title)
        {
            var visits = LoadVisits(username);
            visits.Insert(0, new PageVisit
            {
                VisitedAt = DateTime.UtcNow,
                PagePath = path,
                PageTitle = title
            });
            if (visits.Count > MaxVisitsStored)
                visits = visits.Take(MaxVisitsStored).ToList();
            SaveVisits(username, visits);
        }

        public List<PageVisit> GetRecentVisits(string username, int count = 20)
        {
            return LoadVisits(username).Take(count).ToList();
        }

        // ──────── PRIVATE HELPERS ────────

        private string UserDir(string username) =>
            Path.Combine(_dataRoot, SanitizeName(username));

        private string SessionDir(string username) =>
            Path.Combine(UserDir(username), "sessions");

        private string VisitsFile(string username) =>
            Path.Combine(UserDir(username), "visits.json");

        private List<PageVisit> LoadVisits(string username)
        {
            var file = VisitsFile(username);
            if (!File.Exists(file)) return new List<PageVisit>();
            try { return JsonSerializer.Deserialize<List<PageVisit>>(File.ReadAllText(file), _json) ?? new(); }
            catch { return new List<PageVisit>(); }
        }

        private void SaveVisits(string username, List<PageVisit> visits)
        {
            Directory.CreateDirectory(UserDir(username));
            File.WriteAllText(VisitsFile(username), JsonSerializer.Serialize(visits, _json));
        }

        private static string SanitizeName(string name) =>
            string.Concat(name.Where(c => char.IsLetterOrDigit(c) || c == '_' || c == '-'));

        private static double ComputeTrend(List<SessionResult> sessions)
        {
            if (sessions.Count < 4) return 0;
            var sorted = sessions.OrderBy(s => s.CreatedAt).ToList();
            var half = sorted.Count / 2;
            var older = sorted.Take(half).Average(s => s.OverallAccuracy);
            var newer = sorted.Skip(half).Average(s => s.OverallAccuracy);
            return Math.Round(newer - older, 1);
        }
    }

    public class UserStats
    {
        public int TotalSessions { get; set; }
        public double AverageAccuracy { get; set; }
        public double BestAccuracy { get; set; }
        public DateTime? LastSessionAt { get; set; }
        public double RecentTrend { get; set; }
    }
}
