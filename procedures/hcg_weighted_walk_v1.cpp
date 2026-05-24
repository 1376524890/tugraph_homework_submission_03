#include "lgraph/lgraph.h"

#ifndef __has_include
#define __has_include(x) 0
#endif

#if __has_include("tools/json.hpp")
#include "tools/json.hpp"
#define HCG_HAS_NLOHMANN_JSON 1
using json = nlohmann::json;
#else
#define HCG_HAS_NLOHMANN_JSON 0
#endif

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cctype>
#include <cstdlib>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <limits>
#include <memory>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

using namespace lgraph_api;

namespace {

const char* kProcedureName = "hcg_weighted_walk_v1";
const char* kNodeLabel = "Endpoint";
const char* kEdgeLabel = "COMMUNICATES";
const size_t kEndpointIdFieldId = 0;
const size_t kFlowCountFieldId = 3;
const size_t kTotalBytesFieldId = 13;

struct Params {
    std::string output_path = "/var/lib/lgraph/walks/hcg_walks.txt";
    std::string id_map_path = "/var/lib/lgraph/walks/hcg_node_id_map.csv";
    int walk_length = 20;
    int num_walks = 5;
    double p = 1.0;
    double q = 1.0;
    bool weighted = true;
    std::string weight_field = "flow_count";
    std::string weight_transform = "log1p";
    bool directed = true;
    uint64_t seed = 20260524;
    int64_t max_start_nodes = 10000;
    bool use_endpoint_id_token = true;
    int return_preview_lines = 5;
};

struct Neighbor {
    int64_t vid = 0;
    double weight = 1.0;
    double cumulative = 1.0;
};

struct GraphData {
    std::vector<int64_t> start_nodes;
    std::unordered_map<int64_t, std::string> tokens;
    std::unordered_map<int64_t, std::vector<Neighbor> > adj;
    size_t node_count = 0;
    size_t edge_count = 0;
    std::vector<std::string> warnings;
};

std::string EscapeJson(const std::string& s) {
    std::ostringstream os;
    for (char c : s) {
        switch (c) {
        case '\\': os << "\\\\"; break;
        case '"': os << "\\\""; break;
        case '\n': os << "\\n"; break;
        case '\r': os << "\\r"; break;
        case '\t': os << "\\t"; break;
        default:
            if (static_cast<unsigned char>(c) < 0x20) {
                os << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                   << static_cast<int>(static_cast<unsigned char>(c));
            } else {
                os << c;
            }
        }
    }
    return os.str();
}

std::string ErrorResponse(const std::string& message, const std::string& hint) {
    std::ostringstream os;
    os << "{";
    os << "\"status\":\"error\",";
    os << "\"procedure\":\"" << kProcedureName << "\",";
    os << "\"message\":\"" << EscapeJson(message) << "\",";
    os << "\"hint\":\"" << EscapeJson(hint) << "\"";
    os << "}";
    return os.str();
}

bool FindJsonValue(const std::string& json, const std::string& key, size_t* value_pos, size_t* value_end) {
    const std::string quoted_key = "\"" + key + "\"";
    size_t key_pos = json.find(quoted_key);
    if (key_pos == std::string::npos) return false;
    size_t colon = json.find(':', key_pos + quoted_key.size());
    if (colon == std::string::npos) return false;
    size_t pos = colon + 1;
    while (pos < json.size() && std::isspace(static_cast<unsigned char>(json[pos]))) ++pos;
    if (pos >= json.size()) return false;
    if (json[pos] == '"') {
        size_t end = pos + 1;
        bool escaped = false;
        while (end < json.size()) {
            if (!escaped && json[end] == '"') break;
            escaped = (!escaped && json[end] == '\\');
            if (json[end] != '\\') escaped = false;
            ++end;
        }
        if (end >= json.size()) return false;
        *value_pos = pos;
        *value_end = end + 1;
        return true;
    }
    size_t end = pos;
    while (end < json.size() && json[end] != ',' && json[end] != '}') ++end;
    while (end > pos && std::isspace(static_cast<unsigned char>(json[end - 1]))) --end;
    *value_pos = pos;
    *value_end = end;
    return true;
}

std::string UnquoteJsonString(const std::string& token) {
    if (token.size() < 2 || token.front() != '"' || token.back() != '"') return token;
    std::string out;
    for (size_t i = 1; i + 1 < token.size(); ++i) {
        char c = token[i];
        if (c == '\\' && i + 1 < token.size() - 1) {
            char n = token[++i];
            switch (n) {
            case '"': out.push_back('"'); break;
            case '\\': out.push_back('\\'); break;
            case '/': out.push_back('/'); break;
            case 'n': out.push_back('\n'); break;
            case 'r': out.push_back('\r'); break;
            case 't': out.push_back('\t'); break;
            default: out.push_back(n); break;
            }
        } else {
            out.push_back(c);
        }
    }
    return out;
}

void ReadString(const std::string& json, const std::string& key, std::string* value) {
    size_t pos = 0, end = 0;
    if (FindJsonValue(json, key, &pos, &end)) *value = UnquoteJsonString(json.substr(pos, end - pos));
}

void ReadInt(const std::string& json, const std::string& key, int* value) {
    size_t pos = 0, end = 0;
    if (FindJsonValue(json, key, &pos, &end)) *value = std::atoi(json.substr(pos, end - pos).c_str());
}

void ReadInt64(const std::string& json, const std::string& key, int64_t* value) {
    size_t pos = 0, end = 0;
    if (FindJsonValue(json, key, &pos, &end)) *value = std::atoll(json.substr(pos, end - pos).c_str());
}

void ReadUInt64(const std::string& json, const std::string& key, uint64_t* value) {
    size_t pos = 0, end = 0;
    if (FindJsonValue(json, key, &pos, &end)) *value = static_cast<uint64_t>(std::strtoull(json.substr(pos, end - pos).c_str(), nullptr, 10));
}

void ReadDouble(const std::string& json, const std::string& key, double* value) {
    size_t pos = 0, end = 0;
    if (FindJsonValue(json, key, &pos, &end)) *value = std::atof(json.substr(pos, end - pos).c_str());
}

void ReadBool(const std::string& json, const std::string& key, bool* value) {
    size_t pos = 0, end = 0;
    if (!FindJsonValue(json, key, &pos, &end)) return;
    std::string token = json.substr(pos, end - pos);
    std::transform(token.begin(), token.end(), token.begin(), ::tolower);
    if (token == "true" || token == "1") *value = true;
    if (token == "false" || token == "0") *value = false;
}

Params ParseParams(const std::string& request) {
    Params p;
#if HCG_HAS_NLOHMANN_JSON
    try {
        if (!request.empty()) {
            json input = json::parse(request);
            if (input.find("output_path") != input.end()) p.output_path = input["output_path"].get<std::string>();
            if (input.find("id_map_path") != input.end()) p.id_map_path = input["id_map_path"].get<std::string>();
            if (input.find("walk_length") != input.end()) p.walk_length = input["walk_length"].get<int>();
            if (input.find("num_walks") != input.end()) p.num_walks = input["num_walks"].get<int>();
            if (input.find("p") != input.end()) p.p = input["p"].get<double>();
            if (input.find("q") != input.end()) p.q = input["q"].get<double>();
            if (input.find("weighted") != input.end()) p.weighted = input["weighted"].get<bool>();
            if (input.find("weight_field") != input.end()) p.weight_field = input["weight_field"].get<std::string>();
            if (input.find("weight_transform") != input.end()) p.weight_transform = input["weight_transform"].get<std::string>();
            if (input.find("directed") != input.end()) p.directed = input["directed"].get<bool>();
            if (input.find("seed") != input.end()) p.seed = input["seed"].get<uint64_t>();
            if (input.find("max_start_nodes") != input.end()) p.max_start_nodes = input["max_start_nodes"].get<int64_t>();
            if (input.find("use_endpoint_id_token") != input.end()) p.use_endpoint_id_token = input["use_endpoint_id_token"].get<bool>();
            if (input.find("return_preview_lines") != input.end()) p.return_preview_lines = input["return_preview_lines"].get<int>();
        }
    } catch (const std::exception& e) {
        throw std::runtime_error(std::string("error parsing request JSON: ") + e.what());
    }
#else
    ReadString(request, "output_path", &p.output_path);
    ReadString(request, "id_map_path", &p.id_map_path);
    ReadInt(request, "walk_length", &p.walk_length);
    ReadInt(request, "num_walks", &p.num_walks);
    ReadDouble(request, "p", &p.p);
    ReadDouble(request, "q", &p.q);
    ReadBool(request, "weighted", &p.weighted);
    ReadString(request, "weight_field", &p.weight_field);
    ReadString(request, "weight_transform", &p.weight_transform);
    ReadBool(request, "directed", &p.directed);
    ReadUInt64(request, "seed", &p.seed);
    ReadInt64(request, "max_start_nodes", &p.max_start_nodes);
    ReadBool(request, "use_endpoint_id_token", &p.use_endpoint_id_token);
    ReadInt(request, "return_preview_lines", &p.return_preview_lines);
#endif
    if (p.walk_length < 1) p.walk_length = 1;
    if (p.num_walks < 1) p.num_walks = 1;
    if (p.return_preview_lines < 0) p.return_preview_lines = 0;
    if (p.weight_field != "flow_count" && p.weight_field != "total_bytes") p.weight_field = "flow_count";
    if (p.weight_transform != "none" && p.weight_transform != "log1p" && p.weight_transform != "sqrt") p.weight_transform = "log1p";
    return p;
}

double TransformWeight(double raw, const Params& params) {
    if (!params.weighted || raw <= 0.0 || !std::isfinite(raw)) return 1.0;
    if (params.weight_transform == "log1p") return std::max(1e-12, std::log1p(raw));
    if (params.weight_transform == "sqrt") return std::max(1e-12, std::sqrt(raw));
    return std::max(1e-12, raw);
}

double FieldToDouble(const lgraph_api::FieldData& value, bool* ok) {
    try {
        *ok = true;
        return static_cast<double>(value.AsInt64());
    } catch (...) {
    }
    try {
        *ok = true;
        return value.AsDouble();
    } catch (...) {
    }
    *ok = false;
    return 1.0;
}

size_t WeightFieldId(const Params& params) {
    return params.weight_field == "total_bytes" ? kTotalBytesFieldId : kFlowCountFieldId;
}

std::string VidToken(int64_t vid) {
    std::ostringstream os;
    os << vid;
    return os.str();
}

GraphData LoadGraph(GraphDB& db, const Params& params) {
    GraphData data;
    auto txn = db.CreateReadTxn();
    std::unordered_set<int64_t> endpoint_vids;
    bool warned_endpoint_id = false;
    bool warned_weight = false;
    size_t weight_field_id = WeightFieldId(params);

    for (auto vit = txn.GetVertexIterator(); vit.IsValid(); vit.Next()) {
        int64_t vid = vit.GetId();
        endpoint_vids.insert(vid);
        ++data.node_count;
        std::string token = VidToken(vid);
        if (params.use_endpoint_id_token) {
            try {
                token = vit.GetField(kEndpointIdFieldId).AsString();
                if (token.empty()) token = VidToken(vid);
            } catch (...) {
                if (!warned_endpoint_id) {
                    data.warnings.push_back("endpoint_id is unavailable for at least one Endpoint; vid token is used as fallback.");
                    warned_endpoint_id = true;
                }
            }
        }
        data.tokens[vid] = token;
        if (params.max_start_nodes == 0 || static_cast<int64_t>(data.start_nodes.size()) < params.max_start_nodes) {
            data.start_nodes.push_back(vid);
        }
    }

    for (auto vit = txn.GetVertexIterator(); vit.IsValid(); vit.Next()) {
        int64_t src = vit.GetId();
        for (auto eit = vit.GetOutEdgeIterator(); eit.IsValid(); eit.Next()) {
            int64_t dst = eit.GetDst();
            if (endpoint_vids.find(dst) == endpoint_vids.end()) continue;
            double raw = 1.0;
            if (params.weighted) {
                try {
                    bool ok = false;
                    raw = FieldToDouble(eit.GetField(weight_field_id), &ok);
                    if (!ok && !warned_weight) {
                        data.warnings.push_back("weight field is unavailable or non-numeric for at least one edge; fallback weight 1.0 is used.");
                        warned_weight = true;
                    }
                } catch (...) {
                    if (!warned_weight) {
                        data.warnings.push_back("weight field is unavailable or non-numeric for at least one edge; fallback weight 1.0 is used.");
                        warned_weight = true;
                    }
                    raw = 1.0;
                }
            }
            double w = TransformWeight(raw, params);
            data.adj[src].push_back(Neighbor{dst, w, 0.0});
            if (!params.directed) data.adj[dst].push_back(Neighbor{src, w, 0.0});
            ++data.edge_count;
        }
    }

    for (auto& kv : data.adj) {
        double cumulative = 0.0;
        for (auto& nb : kv.second) {
            cumulative += nb.weight;
            nb.cumulative = cumulative;
        }
    }
    txn.Abort();
    return data;
}

std::string GetVertexToken(lgraph_api::VertexIterator& vit, const Params& params,
                           GraphData* data, bool* warned_endpoint_id) {
    int64_t vid = vit.GetId();
    auto token_it = data->tokens.find(vid);
    if (token_it != data->tokens.end()) return token_it->second;

    std::string token = VidToken(vid);
    if (params.use_endpoint_id_token) {
        try {
            token = vit.GetField(kEndpointIdFieldId).AsString();
            if (token.empty()) token = VidToken(vid);
        } catch (...) {
            if (!*warned_endpoint_id) {
                data->warnings.push_back("endpoint_id is unavailable for at least one Endpoint; vid token is used as fallback.");
                *warned_endpoint_id = true;
            }
        }
    }
    data->tokens[vid] = token;
    return token;
}

void LoadNeighborsForVertex(Transaction& txn, int64_t vid, const Params& params, GraphData* data,
                            bool* warned_weight, bool* warned_endpoint_id) {
    if (data->adj.find(vid) != data->adj.end()) return;

    std::vector<Neighbor> neighbors;
    auto vit = txn.GetVertexIterator(vid);
    if (!vit.IsValid()) {
        data->adj[vid] = neighbors;
        return;
    }
    GetVertexToken(vit, params, data, warned_endpoint_id);

    size_t weight_field_id = WeightFieldId(params);
    for (auto eit = vit.GetOutEdgeIterator(); eit.IsValid(); eit.Next()) {
        int64_t dst = eit.GetDst();
        double raw = 1.0;
        if (params.weighted) {
            try {
                bool ok = false;
                raw = FieldToDouble(eit.GetField(weight_field_id), &ok);
                if (!ok && !*warned_weight) {
                    data->warnings.push_back("weight field is unavailable or non-numeric for at least one edge; fallback weight 1.0 is used.");
                    *warned_weight = true;
                }
            } catch (...) {
                if (!*warned_weight) {
                    data->warnings.push_back("weight field is unavailable or non-numeric for at least one edge; fallback weight 1.0 is used.");
                    *warned_weight = true;
                }
                raw = 1.0;
            }
        }
        neighbors.push_back(Neighbor{dst, TransformWeight(raw, params), 0.0});
        ++data->edge_count;
    }
    if (!params.directed) {
        for (auto eit = vit.GetInEdgeIterator(); eit.IsValid(); eit.Next()) {
            int64_t src = eit.GetSrc();
            double raw = 1.0;
            if (params.weighted) {
                try {
                    bool ok = false;
                    raw = FieldToDouble(eit.GetField(weight_field_id), &ok);
                    if (!ok && !*warned_weight) {
                        data->warnings.push_back("weight field is unavailable or non-numeric for at least one edge; fallback weight 1.0 is used.");
                        *warned_weight = true;
                    }
                } catch (...) {
                    if (!*warned_weight) {
                        data->warnings.push_back("weight field is unavailable or non-numeric for at least one edge; fallback weight 1.0 is used.");
                        *warned_weight = true;
                    }
                    raw = 1.0;
                }
            }
            neighbors.push_back(Neighbor{src, TransformWeight(raw, params), 0.0});
            ++data->edge_count;
        }
    }

    double cumulative = 0.0;
    for (auto& nb : neighbors) {
        cumulative += nb.weight;
        nb.cumulative = cumulative;
    }
    data->adj[vid] = neighbors;
}

GraphData LoadStartNodesOnly(GraphDB& db, const Params& params) {
    GraphData data;
    auto txn = db.CreateReadTxn();
    bool warned_endpoint_id = false;
    for (auto vit = txn.GetVertexIterator(); vit.IsValid(); vit.Next()) {
        int64_t vid = vit.GetId();
        data.start_nodes.push_back(vid);
        GetVertexToken(vit, params, &data, &warned_endpoint_id);
        if (params.max_start_nodes > 0 &&
            static_cast<int64_t>(data.start_nodes.size()) >= params.max_start_nodes) {
            break;
        }
    }
    data.node_count = data.tokens.size();
    data.warnings.push_back("limited mode is enabled; node_count and edge_count report only vertices/edges touched by sampled walks.");
    txn.Abort();
    return data;
}

int64_t SampleFirstOrder(const std::vector<Neighbor>& neighbors, std::mt19937_64* rng) {
    if (neighbors.empty()) return -1;
    double total = neighbors.back().cumulative;
    if (total <= 0.0 || !std::isfinite(total)) return neighbors.front().vid;
    std::uniform_real_distribution<double> dist(0.0, total);
    double r = dist(*rng);
    auto it = std::lower_bound(neighbors.begin(), neighbors.end(), r,
                               [](const Neighbor& nb, double value) { return nb.cumulative < value; });
    if (it == neighbors.end()) return neighbors.back().vid;
    return it->vid;
}

std::string JoinWalk(const std::vector<int64_t>& walk, const std::unordered_map<int64_t, std::string>& tokens) {
    std::ostringstream os;
    for (size_t i = 0; i < walk.size(); ++i) {
        if (i) os << ' ';
        auto it = tokens.find(walk[i]);
        os << (it == tokens.end() ? VidToken(walk[i]) : it->second);
    }
    return os.str();
}

void WriteIdMap(const std::string& path, const std::unordered_map<int64_t, std::string>& tokens) {
    std::ofstream out(path.c_str());
    if (!out) throw std::runtime_error("cannot open id_map_path for writing: " + path);
    out << "vid,token\n";
    for (const auto& kv : tokens) out << kv.first << ",\"" << EscapeJson(kv.second) << "\"\n";
}

std::string BuildOkResponse(const Params& params, const GraphData& data, size_t walk_count,
                            const std::vector<std::string>& preview, double elapsed_seconds) {
    std::ostringstream os;
    os << std::fixed << std::setprecision(6);
    os << "{";
    os << "\"status\":\"ok\",";
    os << "\"procedure\":\"" << kProcedureName << "\",";
    os << "\"graph\":\"hcg\",";
    os << "\"node_label\":\"" << kNodeLabel << "\",";
    os << "\"edge_label\":\"" << kEdgeLabel << "\",";
    os << "\"node_count\":" << data.node_count << ",";
    os << "\"edge_count\":" << data.edge_count << ",";
    os << "\"start_node_count\":" << data.start_nodes.size() << ",";
    os << "\"walk_count\":" << walk_count << ",";
    os << "\"walk_length\":" << params.walk_length << ",";
    os << "\"num_walks\":" << params.num_walks << ",";
    os << "\"weighted\":" << (params.weighted ? "true" : "false") << ",";
    os << "\"weight_field\":\"" << EscapeJson(params.weight_field) << "\",";
    os << "\"weight_transform\":\"" << EscapeJson(params.weight_transform) << "\",";
    os << "\"directed\":" << (params.directed ? "true" : "false") << ",";
    os << "\"output_path\":\"" << EscapeJson(params.output_path) << "\",";
    os << "\"id_map_path\":\"" << EscapeJson(params.id_map_path) << "\",";
    os << "\"preview\":[";
    for (size_t i = 0; i < preview.size(); ++i) {
        if (i) os << ",";
        os << "\"" << EscapeJson(preview[i]) << "\"";
    }
    os << "],";
    os << "\"warnings\":[";
    for (size_t i = 0; i < data.warnings.size(); ++i) {
        if (i) os << ",";
        os << "\"" << EscapeJson(data.warnings[i]) << "\"";
    }
    os << "],";
    os << "\"elapsed_seconds\":" << elapsed_seconds;
    os << "}";
    return os.str();
}

}  // namespace

extern "C" LGAPI bool Process(GraphDB& db, const std::string& request, std::string& response) {
    auto start_time = std::chrono::steady_clock::now();
    try {
        Params params = ParseParams(request);
        bool limited_mode = params.max_start_nodes > 0;
        GraphData data = limited_mode ? LoadStartNodesOnly(db, params) : LoadGraph(db, params);

        std::ofstream walks_out(params.output_path.c_str());
        if (!walks_out) {
            response = ErrorResponse("cannot open output_path for writing: " + params.output_path,
                                     "Create the parent directory inside the TuGraph server/container and grant write permission.");
            return true;
        }

        std::mt19937_64 rng(params.seed);
        std::vector<std::string> preview;
        size_t walk_count = 0;
        bool warned_weight = false;
        bool warned_endpoint_id = false;
        std::unique_ptr<Transaction> lazy_txn;
        if (limited_mode) lazy_txn.reset(new Transaction(db.CreateReadTxn()));
        for (int round = 0; round < params.num_walks; ++round) {
            for (int64_t start : data.start_nodes) {
                std::vector<int64_t> walk;
                walk.reserve(static_cast<size_t>(params.walk_length));
                walk.push_back(start);
                while (static_cast<int>(walk.size()) < params.walk_length) {
                    if (limited_mode) {
                        LoadNeighborsForVertex(*lazy_txn, walk.back(), params, &data,
                                               &warned_weight, &warned_endpoint_id);
                    }
                    auto it = data.adj.find(walk.back());
                    if (it == data.adj.end() || it->second.empty()) break;
                    int64_t next = SampleFirstOrder(it->second, &rng);
                    if (next < 0) break;
                    walk.push_back(next);
                }
                std::string line = JoinWalk(walk, data.tokens);
                walks_out << line << "\n";
                if (static_cast<int>(preview.size()) < params.return_preview_lines) preview.push_back(line);
                ++walk_count;
            }
        }
        if (limited_mode) {
            data.node_count = data.tokens.size();
            lazy_txn->Abort();
        }
        WriteIdMap(params.id_map_path, data.tokens);
        walks_out.close();
        if (!walks_out) {
            response = ErrorResponse("failed while writing output_path: " + params.output_path,
                                     "Check disk space and write permission in the TuGraph server/container.");
            return true;
        }

        double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - start_time).count();
        response = BuildOkResponse(params, data, walk_count, preview, elapsed);
        return true;
    } catch (const std::exception& e) {
        response = ErrorResponse(e.what(), "Check HCG schema, field names, output paths, and WebUI C++ API compatibility.");
        return true;
    } catch (...) {
        response = ErrorResponse("unknown exception", "Check TuGraph server logs for the C++ stored procedure error.");
        return true;
    }
}
