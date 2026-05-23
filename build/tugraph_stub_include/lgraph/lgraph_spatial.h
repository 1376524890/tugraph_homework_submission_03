#pragma once

#include <stdexcept>
#include <string>

namespace lgraph_api {

struct Cartesian {};
struct Wgs84 {};

enum class SpatialType {
    NUL = 0,
    POINT = 1,
    LINESTRING = 2,
    POLYGON = 3
};

enum class SRID {
    NUL = 0,
    WGS84 = 4326,
    CARTESIAN = 7203
};

inline SRID ExtractSRID(const std::string&) {
    return SRID::NUL;
}

inline SpatialType ExtractType(const std::string&) {
    return SpatialType::NUL;
}

template <typename SRID_Type>
class Point;

template <typename SRID_Type>
class LineString;

template <typename SRID_Type>
class Polygon;

template <typename SRID_Type>
class Spatial {
 public:
    explicit Spatial(const std::string& ewkb) : ewkb_(ewkb) {}
    Spatial(SRID, SpatialType, int, std::string content) : ewkb_(std::move(content)) {}

    std::string AsEWKB() const { return ewkb_; }
    std::string AsEWKT() const { return ewkb_; }
    std::string ToString() const { return ewkb_; }
    SpatialType GetType() const { return SpatialType::NUL; }
    double Distance(Spatial<SRID_Type>&) { return 0.0; }
    bool operator==(const Spatial<SRID_Type>& other) const { return ewkb_ == other.ewkb_; }

 private:
    std::string ewkb_;
};

template <typename SRID_Type>
class Point {
 public:
    explicit Point(const std::string& ewkb) : ewkb_(ewkb) {}
    Point(SRID, SpatialType, int, std::string& content) : ewkb_(content) {}
    Point(double, double, SRID&) {}

    std::string AsEWKB() const { return ewkb_; }
    std::string AsEWKT() const { return ewkb_; }
    std::string ToString() const { return ewkb_; }
    double Distance(Point<SRID_Type>&) { return 0.0; }
    double Distance(LineString<SRID_Type>&) { return 0.0; }
    double Distance(Polygon<SRID_Type>&) { return 0.0; }
    bool operator==(const Point<SRID_Type>& other) const { return ewkb_ == other.ewkb_; }

 private:
    std::string ewkb_;
};

template <typename SRID_Type>
class LineString {
 public:
    explicit LineString(const std::string& ewkb) : ewkb_(ewkb) {}
    LineString(SRID, SpatialType, int, std::string& content) : ewkb_(content) {}

    std::string AsEWKB() const { return ewkb_; }
    std::string AsEWKT() const { return ewkb_; }
    std::string ToString() const { return ewkb_; }
    double Distance(Point<SRID_Type>&) { return 0.0; }
    double Distance(LineString<SRID_Type>&) { return 0.0; }
    double Distance(Polygon<SRID_Type>&) { return 0.0; }
    bool operator==(const LineString<SRID_Type>& other) const { return ewkb_ == other.ewkb_; }

 private:
    std::string ewkb_;
};

template <typename SRID_Type>
class Polygon {
 public:
    explicit Polygon(const std::string& ewkb) : ewkb_(ewkb) {}
    Polygon(SRID, SpatialType, int, std::string& content) : ewkb_(content) {}

    std::string AsEWKB() const { return ewkb_; }
    std::string AsEWKT() const { return ewkb_; }
    std::string ToString() const { return ewkb_; }
    double Distance(Point<SRID_Type>&) { return 0.0; }
    double Distance(LineString<SRID_Type>&) { return 0.0; }
    double Distance(Polygon<SRID_Type>&) { return 0.0; }
    bool operator==(const Polygon<SRID_Type>& other) const { return ewkb_ == other.ewkb_; }

 private:
    std::string ewkb_;
};

}  // namespace lgraph_api
