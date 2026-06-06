using System;
using System.Collections.Generic;

namespace PickleballWebApp.Models
{
    public class SessionResult
    {
        public string Id { get; set; } = string.Empty;
        public DateTime CreatedAt { get; set; }
        public string Username { get; set; } = string.Empty;
        public string PresetName { get; set; } = string.Empty;
        public string Mode { get; set; } = "camera"; // "camera" or "video"
        public double OverallAccuracy { get; set; }
        public int NumFrames { get; set; }
        public double DurationSec { get; set; }
        public List<string> Feedback { get; set; } = new();
        public List<double?> PerJointAccuracy { get; set; } = new();
    }
}
