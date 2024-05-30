# -*- coding: utf-8 -*-
"""One body can be defined by one of the two following shapes:
    * a biaxial body
    * a triaxial body


At each shape, we can define three reference frames :
    * planetocentric frame with a sphere for interoperability purpose
    * planetocentric frame
    * planetographic frame

For a spherical shape, the planetocentric latitude and the planetographic
latitude are identical. So a planetographic latitude is used.

Planetographic longitude is usually defined such that the sub-observer
longitude increases with time as seen by a distant, fixed observer

Positive logitudes in one direction are defined with the following rule

.. uml::
    :caption: Positive longitude rules

    start

    if (historical reason or IAU_code >= 9000?) then (yes)
    :East;
    stop
    else (no )
    if (ocentric frame ?) then (yes)
        :East;
        stop
    else (no)
        if (rotation == "Direct" ?) then (yes)
            :West;
            stop
        elif (rotation == "Retrograde" ?) then (yes)
            :East;
            stop
        else (no)
            :None;
            stop
        endif
    endif
    endif

"""
# pylint: disable=too-many-lines
from abc import ABCMeta
from abc import abstractmethod
from abc import abstractproperty
from enum import Enum
from string import Template
from typing import cast
from typing import Dict
from typing import Generator
from typing import List
from typing import Optional
from typing import Tuple

import numpy as np  # pylint: disable=import-error
import pandas as pd  # pylint: disable=import-error

from .body import IAU_REPORT
from .body import IBody
from .body import ReferenceShape
from .datum import Anchor
from .datum import Datum


class ICrs(metaclass=ABCMeta):
    """High level class that handles a Coordinate Reference System."""

    @classmethod
    def __subclasshook__(cls, subclass):
        return (
            hasattr(subclass, "iau_code")
            and callable(subclass.iau_code)
            and hasattr(subclass, "wkt")
            and callable(subclass.wkt)
            and hasattr(subclass, "datum")
            and callable(subclass.datum)
            or NotImplemented
        )

    @abstractproperty  # pylint: disable=no-self-use,bad-option-value,deprecated-decorator
    def iau_code(self) -> int:
        """IAU code.

        :getter: Returns the IAU code
        :type: int
        """
        raise NotImplementedError("Not implemented")

    @abstractproperty  # pylint: disable=no-self-use,bad-option-value,deprecated-decorator
    def datum(self) -> Datum:
        """Datum.

        :getter: Returns the datum
        :type: Datum
        """
        raise NotImplementedError("Not implemented")

    @abstractmethod
    def wkt(self) -> str:
        """Returns the WKT description.

        :getter: Returns the WKT description
        :type: str
        """
        raise NotImplementedError("Not implemented")


class CrsType(Enum):
    """Type of CRS."""

    OCENTRIC = "Ocentric"
    OGRAPHIC = "Ographic"


class BodyCrsCode(Enum):
    """Code related to the shape and the coordinate reference system."""

    SPHERE_OCENTRIC = ("Sphere", CrsType.OCENTRIC.value, 0)
    ELLIPSE_OGRAPHIC = ("Ellipse", CrsType.OGRAPHIC.value, 1)
    ELLIPSE_OCENTRIC = ("Ellipse", CrsType.OCENTRIC.value, 2)
    TRIAXIAL_OGRAPHIC = ("Triaxial", CrsType.OGRAPHIC.value, 3)
    TRIAXIAL_OCENTRIC = ("Triaxial", CrsType.OCENTRIC.value, 4)

    def __init__(self, shape: str, reference: str, code: int):
        """Creates the enum

        Args:
            shape (str): shape
            reference (str): referential
            code (int): code of (shape, referential)
        """
        self.shape: str = shape
        self.reference: str = reference
        self.code = code

    def get_code(self, naif_code: int) -> int:
        """Compute the code of the body based on the Naif code.

        Args:
            naif_code (int): naif code

        Returns:
            int: the code of the body
        """
        return naif_code * 100 + self.code


@ICrs.register
class BodyCrs(ICrs):
    """The description of the body Coordinate Reference System."""

    TEMPLATE_OGRAPHIC = """GEOGCRS["$name ($version) / Ographic",
    $datum,
\tCS[ellipsoidal, 2],
\t    AXIS["geodetic latitude (Lat)", north,
\t        ORDER[1],
\t        ANGLEUNIT["degree", 0.0174532925199433]],
\t    AXIS["geodetic longitude (Lon)", $direction,
\t        ORDER[2],
\t        ANGLEUNIT["degree", 0.0174532925199433]],
\tID["IAU", $number, $version],
\tREMARK["$remark"]]"""

    TEMPLATE_OCENTRIC = """GEODCRS["$name ($version) / Ocentric",
    $datum,
\tCS[spherical, 2],
\t    AXIS["planetocentric latitude (U)", north,
\t        ORDER[1],
\t        ANGLEUNIT["degree", 0.0174532925199433]],
\t    AXIS["planetocentric longitude (V)", east,
\t        ORDER[2],
\t        ANGLEUNIT["degree", 0.0174532925199433]],
\tID["IAU", $number, $version],
\tREMARK["$remark"]]"""

    TEMPLATE_SPHERE = """GEOGCRS["$name ($version) - Sphere ",
    $datum,
\tCS[ellipsoidal, 2],
\t    AXIS["geodetic latitude (Lat)", north,
\t        ORDER[1],
\t        ANGLEUNIT["degree", 0.0174532925199433]],
\t    AXIS["geodetic longitude (Lon)", east,
\t        ORDER[2],
\t        ANGLEUNIT["degree", 0.0174532925199433]],
\tID["IAU", $number, $version],
\tREMARK["$remark"]]"""

    def __init__(
        self, datum: Datum, number_body: int, direction: str, crs_type: CrsType
    ):
        """Create a Coordinate Reference System for a celestial body

        Args:
            datum (Datum): datum of the body
            number_body (int): IAU code
            direction (str): rotation sens of the body
            crs_type (CrsType): type of CRS
        """
        self.__datum: Datum = datum
        self.__crs_type: CrsType = crs_type
        self.__direction: str = self._create_direction(
            datum.name, direction, crs_type, number_body
        )
        self.__name: str = datum.name

        template, number = self._get_template_and_number(number_body)
        self.__number: int = number
        self.__template: str = template

    def _get_template_and_number(  # pylint: disable=no-self-use
        self, naif_code: int
    ) -> Tuple[str, int]:
        """Returns the template and the number

        Args:
            naif_code (int): naif code

        Raises:
            ValueError: "Unknown shape or CRS

        Returns:
            Tuple[str, int]: template and number
        """
        template: str
        number: int

        if self.crs_type == CrsType.OCENTRIC:
            if self.datum.body.shape == ReferenceShape.SPHERE:
                template = BodyCrs.TEMPLATE_SPHERE
                number = BodyCrsCode.SPHERE_OCENTRIC.get_code(naif_code)
            elif self.datum.body.shape == ReferenceShape.ELLIPSE:
                template = BodyCrs.TEMPLATE_OCENTRIC
                number = BodyCrsCode.ELLIPSE_OCENTRIC.get_code(naif_code)
            elif self.datum.body.shape == ReferenceShape.TRIAXIAL:
                template = BodyCrs.TEMPLATE_OCENTRIC
                number = BodyCrsCode.TRIAXIAL_OCENTRIC.get_code(naif_code)
            else:
                raise ValueError(
                    f"Unknown shape : {self.datum.body.shape} for {self.crs_type}"
                )
        elif self.crs_type == CrsType.OGRAPHIC:
            template = BodyCrs.TEMPLATE_OGRAPHIC
            if self.datum.body.shape == ReferenceShape.ELLIPSE:
                number = BodyCrsCode.ELLIPSE_OGRAPHIC.get_code(naif_code)
            elif self.datum.body.shape == ReferenceShape.TRIAXIAL:
                number = BodyCrsCode.TRIAXIAL_OGRAPHIC.get_code(naif_code)
            else:
                raise ValueError(
                    f"Unknown shape : {self.datum.body.shape} for {self.crs_type}"
                )
        else:
            raise ValueError(f"Unknown CRS : {self.crs_type}")

        return template, number

    def _create_direction(
        self,
        name: str,
        rotation: str,
        crs_type: CrsType,
        number_body: int,
    ):  # pylint: disable=no-self-use
        """Returns the direction sens according to the rotation.

        Args:
            name (str): body name
            rotation (str): rotation of the body
            crs_type (CrsType): Type of CRS
            number_body (int): IAU code of the body


        Returns:
            str: _description_
        """
        direction: str
        # longitude ographic is always to East for small bodies, comets, dwarf planets
        # historical reason for SUN, EARTH and MOON
        if number_body >= 90000 or name.upper() in ["SUN", "EARTH", "MOON"]:
            direction = "east"

        # always to east in ocentric
        elif crs_type == CrsType.OCENTRIC:
            direction = "east"

        # when Direct => West
        elif rotation == "Direct":
            direction = "west"

        elif rotation == "Retrograde":
            direction = "east"

        # last case : we do not know
        else:
            direction = None
        return direction

    def _create_remark(self) -> str:
        """Returns the content of the remark.

        Returns:
            str: the content of the remark
        """
        result: str
        if self.datum.body.warning is None:
            result = IAU_REPORT.SOURCE_IAU
        else:
            result = self.datum.body.warning + IAU_REPORT.SOURCE_IAU
        return result

    @property
    def crs_type(self) -> CrsType:
        """Returns the type of CRS.

        Returns:
            CrsType: Type of CRS
        """
        return self.__crs_type

    @property
    def name(self) -> str:
        """Returns the name of the body.

        Returns:
            str: the name of the body
        """
        return self.__name

    @property
    def datum(self) -> Datum:
        """Returns the datum of the body.

        Returns:
            Datum: the datum of the body
        """
        return self.__datum

    @property
    def direction(self) -> Optional[str]:
        """Returns the direction where the longitude is counted positively.

        Returns:
            Optional[str]: the direction
        """
        return self.__direction

    @property
    def iau_code(self) -> int:
        """Returns the IAU code.

        Returns:
            str: the IAU code
        """
        return self.__number

    def wkt(self) -> str:
        """Returns the WKT of the celestial body.

        Returns:
            str: the WKT of the celestial body
        """
        assert (
            self.direction is not None
        ), f"Not possible to create the {self.crs_type} : there is not axis direction for {self.datum.name}"
        biaxialbody_template = Template(self.__template)
        datum = biaxialbody_template.substitute(
            name=self.name,
            version=IAU_REPORT.VERSION,
            datum=self.datum.wkt(),
            number=self.iau_code,
            direction=self.direction,
            remark=self._create_remark(),
        )
        return datum


class Planetocentric:
    """Computes the planetocentric coordinate reference system."""

    def __init__(self, row: pd.Series, ref_shape: ReferenceShape):
        """Creates a description of a planetocentric Coordinate Reference
        System.

        Args:
            row (pd.Series): description of the current body
            ref_shape(ReferenceShape) : Reference of the shape

        Returns:
            ICrs: Coordinate Reference System description
        """
        self.__row: pd.dataframe = row
        self.__ref_shape: ReferenceShape = ref_shape
        self.__crs: BodyCrs = self._crs()

    @property
    def row(self) -> pd.DataFrame:
        """Description of the current body.

        Returns:
            str: Description of the current body
        """
        return self.__row

    @property
    def ref_shape(self) -> ReferenceShape:
        """Shape related to this coordinate reference system.

        Returns:
            ReferenceShape: type of shape
        """
        return self.__ref_shape

    @property
    def crs_type(self) -> CrsType:
        """Type of coordinate reference system.

        Returns:
            CrsType: type of coordinate reference system
        """
        return CrsType.OCENTRIC

    @property
    def crs(self) -> BodyCrs:
        """Coordinate reference system of the body.

        Returns:
            BodyCrs: coordinate reference system of the body
        """
        return self.__crs

    def _create_body(self) -> IBody:
        """Creates the description of the coordinate reference system for the
        body.

        Returns:
            IBody: the coordinate reference system for the body
        """
        return IBody.create(
            self.ref_shape,
            self.row["Body"],
            self.row["IAU2015_Semimajor"],
            self.row["IAU2015_Semiminor"],
            self.row["IAU2015_Axisb"],
            self.row["IAU2015_Mean"],
        )

    def _create_datum(self, body: IBody) -> Datum:
        """Creates the description of the datum related to the body.

        Args:
            body (IBody): the body

        Returns:
            Datum: the datum related to the body
        """
        anchor: Anchor = Anchor(
            f"{self.row['origin_long_name']} : {self.row['origin_lon_pos']}"
        )
        return Datum.create(self.row["Body"], body, anchor)

    def _create_crs(self, datum: Datum) -> BodyCrs:
        """Creates a description of the planetocentric reference system based
        on the datum.

        Args:
            datum (Datum): datum of the body

        Returns:
            BodyCrs: the planetocentric reference system based on the datum
        """
        return BodyCrs(
            datum,
            self.row["Naif_id"],
            self.row["rotation"],
            CrsType.OCENTRIC,
        )

    def _crs(self) -> BodyCrs:
        """Creates a description of a planetocentric Coordinate Reference
        System.

        Returns:
            BodyCrs: Coordinate Reference System description of the body
        """
        shape: IBody = self._create_body()
        datum: Datum = self._create_datum(shape)
        crs: BodyCrs = self._create_crs(datum)
        return crs

    def wkt(self) -> str:
        """Returns the WKT of the coordinate reference system.

        Returns:
            str: the WKT of the coordinate reference system
        """
        return self.__crs.wkt()


class Planetographic(Planetocentric):
    """Computes the planetographic coordinate reference system."""

    @property
    def crs_type(self) -> CrsType:
        """Type of coordinate reference system.

        Returns:
            CrsType: type of coordinate reference system
        """
        return CrsType.OGRAPHIC

    def _create_crs(self, datum: Datum) -> BodyCrs:
        """Creates a planetographic coordinate reference system based on a
        datum.

        Args:
            datum (Datum): datum of the body

        Returns:
            BodyCrs: planetographic coordinate reference system
        """
        return BodyCrs(
            datum,
            self.row["Naif_id"],
            self.row["rotation"],
            CrsType.OGRAPHIC,
        )


class Conversion:
    """Projection elements."""

    TEMPLATE_PARAMETER = """PARAMETER["$parameter_name", $parameter_value,
            $unit,
            ID["$authority", $authority_code]]"""

    TEMPLATE_CONVERSION = """CONVERSION["$conversion_name",
        METHOD["$method_name",
            ID["$authority", $authority_code]],
        $params],"""

    def __init__(
        self,
        conversion_name: str,
        method_name: str,
        method_id: str,
        projection: List[str],
    ) -> None:
        """Creates the projection elements.

        Args:
            conversion_name (str): name of the projection
            method_name (str): name of the method
            method_id (str): method ID
            projection (List[str]): projection elements
        """
        self.__conversion_name = conversion_name
        self.__method_name = method_name
        self.__method_id = method_id
        self.__projection = projection

    @property
    def conversion_name(self) -> str:
        """Returns the conversion name.

        Returns:
            str: the conversion
        """
        return self.__conversion_name

    @property
    def method_name(self) -> str:
        """Returns the method name.

        Returns:
            str: the method name
        """
        return self.__method_name

    @property
    def method_id(self) -> str:
        """Returns the method ID.

        Returns:
            str: the method ID
        """
        return self.__method_id

    @property
    def projection(self) -> List[str]:
        """Returns the projection elements.

        Returns:
            List[str]: the projection elements
        """
        return self.__projection

    def wkt(self) -> str:
        """Returns the WKT of the projection elements.

        Returns:
            str: the WKT
        """
        parameter_template = Template(Conversion.TEMPLATE_PARAMETER)
        parameters = np.array(
            [
                param
                for param in self.projection[3 : len(self.projection)]
                if param is not None
            ]
        )
        parameters = parameters.reshape(int(len(parameters) / 2), 2)
        params: List[str] = list()
        for parameter in parameters:
            method_and_map: List[
                str
            ] = ProjectionBody.METHOD_AND_PARAM_MAPPING[parameter[0]]
            param: str = parameter_template.substitute(
                parameter_name=parameter[0],
                parameter_value=parameter[1],
                unit=method_and_map[2],
                authority=method_and_map[0],
                authority_code=method_and_map[1],
            )
            params.append(param)
        conversion_template = Template(Conversion.TEMPLATE_CONVERSION)

        conversion = conversion_template.substitute(
            conversion_name=self.projection[1],
            method_name=self.projection[2],
            authority=ProjectionBody.METHOD_AND_PARAM_MAPPING[
                self.projection[2]
            ][0],
            authority_code=ProjectionBody.METHOD_AND_PARAM_MAPPING[
                self.projection[2]
            ][1],
            params=",\n\t\t".join(params),
        )
        return conversion


@ICrs.register
class ProjectionBody(ICrs):
    """Coordinate Reference System of the projected body."""

    PROJECTION_DATA = [
        [
            10,
            "Equirectangular, clon = 0",
            "Equidistant Cylindrical",
            "Latitude of 1st standard parallel",
            0,
            "Longitude of natural origin",
            0,
            "False easting",
            0,
            "False northing",
            0,
            None,
            None,
            None,
            None,
        ],
        [
            15,
            "Equirectangular, clon = 180",
            "Equidistant Cylindrical",
            "Latitude of 1st standard parallel",
            0,
            "Longitude of natural origin",
            180,
            "False easting",
            0,
            "False northing",
            0,
            None,
            None,
            None,
            None,
        ],
        [
            20,
            "Sinusoidal, clon = 0",
            "Sinusoidal",
            "Longitude of natural origin",
            0,
            "False easting",
            0,
            "False northing",
            0,
            None,
            None,
            None,
            None,
            None,
            None,
        ],
        [
            25,
            "Sinusoidal, clon = 180",
            "Sinusoidal",
            "Longitude of natural origin",
            180,
            "False easting",
            0,
            "False northing",
            0,
            None,
            None,
            None,
            None,
            None,
            None,
        ],
        [
            30,
            "North Polar",
            "Polar Stereographic (variant A)",
            "Latitude of natural origin",
            90,
            "Longitude of natural origin",
            0,
            "Scale factor at natural origin",
            1,
            "False easting",
            0,
            "False northing",
            0,
            None,
            None,
        ],
        [
            35,
            "South Polar",
            "Polar Stereographic (variant A)",
            "Latitude of natural origin",
            -90,
            "Longitude of natural origin",
            0,
            "Scale factor at natural origin",
            1,
            "False easting",
            0,
            "False northing",
            0,
            None,
            None,
        ],
        [
            40,
            "Mollweide, clon = 0",
            "Mollweide",
            "Longitude of natural origin",
            0,
            "False easting",
            0,
            "False northing",
            0,
            None,
            None,
            None,
            None,
            None,
            None,
        ],
        [
            45,
            "Mollweide, clon = 180",
            "Mollweide",
            "Longitude of natural origin",
            180,
            "False easting",
            0,
            "False northing",
            0,
            None,
            None,
            None,
            None,
            None,
            None,
        ],
        [
            50,
            "Robinson, clon = 0",
            "Robinson",
            "Longitude of natural origin",
            0,
            "False easting",
            0,
            "False northing",
            0,
            None,
            None,
            None,
            None,
            None,
            None,
        ],
        [
            55,
            "Robinson, clon = 180",
            "Robinson",
            "Longitude of natural origin",
            180,
            "False easting",
            0,
            "False northing",
            0,
            None,
            None,
            None,
            None,
            None,
            None,
        ],
        [
            60,
            "Tranverse Mercator",
            "Transverse Mercator",
            "Latitude of natural origin",
            0,
            "Longitude of natural origin",
            0,
            "Scale factor at natural origin",
            1,
            "False easting",
            0,
            "False northing",
            0,
            None,
            None,
        ],
        [
            65,
            "Orthographic, clon = 0",
            "Orthographic",
            "Latitude of natural origin",
            0,
            "Longitude of natural origin",
            0,
            "False easting",
            0,
            "False northing",
            0,
            None,
            None,
            None,
            None,
        ],
        [
            70,
            "Orthographic, clon = 180",
            "Orthographic",
            "Latitude of natural origin",
            0,
            "Longitude of natural origin",
            180,
            "False easting",
            0,
            "False northing",
            0,
            None,
            None,
            None,
            None,
        ],
        [
            75,
            "Lambert Conic Conformal",
            "Lambert Conic Conformal (2SP)",
            "Latitude of false origin",
            40,
            "Longitude of false origin",
            0,
            "Latitude of 1st standard parallel",
            20,
            "Latitude of 2nd standard parallel",
            60,
            "Easting at false origin",
            0,
            "Northing at false origin",
            0,
        ],
        [
            80,
            "Lambert Azimuthal Equal Area",
            "Lambert Azimuthal Equal Area",
            "Latitude of natural origin",
            40,
            "Longitude of natural origin",
            0,
            "False easting",
            0,
            "False northing",
            0,
            None,
            None,
            None,
            None,
        ],
        [
            85,
            "Albers Equal Area",
            "Albers Equal Area",
            "Latitude of false origin",
            40,
            "Longitude of false origin",
            0,
            "Latitude of 1st standard parallel",
            20,
            "Latitude of 2nd standard parallel",
            60,
            "Easting at false origin",
            0,
            "Northing at false origin",
            0,
        ],
        [
            90,
            "Mercator",
            "Mercator (Spherical)",
            "Latitude of natural origin",
            0,
            "Longitude of natural origin",
            0,
            "False easting",
            0,
            "False northing",
            0,
            None,
            None,
            None,
            None,
        ],
    ]

    METHOD_AND_PARAM_MAPPING: Dict[str, List] = {
        "Mercator (Spherical)": ["EPSG", 1026],
        "Lambert Azimuthal Equal Area (Spherical)": ["EPSG", 1027],
        "Equidistant Cylindrical": ["EPSG", 1028],
        "Equidistant Cylindrical (Spherical)": ["EPSG", 1029],
        "Scale factor at natural origin": [
            "EPSG",
            8805,
            'SCALEUNIT["unity",1,ID["EPSG", 9201]]',
        ],
        "False easting": [
            "EPSG",
            8806,
            'LENGTHUNIT["metre",1,ID["EPSG", 9001]]',
        ],
        "False northing": [
            "EPSG",
            8807,
            'LENGTHUNIT["metre",1,ID["EPSG", 9001]]',
        ],
        "Latitude of natural origin": [
            "EPSG",
            8801,
            'ANGLEUNIT["degree",0.0174532925199433,ID["EPSG", 9122]]',
        ],
        "Longitude of natural origin": [
            "EPSG",
            8802,
            'ANGLEUNIT["degree",0.0174532925199433,ID["EPSG", 9122]]',
        ],
        "Latitude of false origin": [
            "EPSG",
            8821,
            'ANGLEUNIT["degree",0.0174532925199433,ID["EPSG", 9122]]',
        ],
        "Longitude of false origin": [
            "EPSG",
            8822,
            'ANGLEUNIT["degree",0.0174532925199433,ID["EPSG", 9122]]',
        ],
        "Latitude of 1st standard parallel": [
            "EPSG",
            8823,
            'ANGLEUNIT["degree",0.0174532925199433,ID["EPSG", 9122]]',
        ],
        "Latitude of 2nd standard parallel": [
            "EPSG",
            8824,
            'ANGLEUNIT["degree",0.0174532925199433,ID["EPSG", 9122]]',
        ],
        "Easting at false origin": [
            "EPSG",
            8826,
            'LENGTHUNIT["metre",1,ID["EPSG", 9001]]',
        ],
        "Northing at false origin": [
            "EPSG",
            8827,
            'LENGTHUNIT["metre",1,ID["EPSG", 9001]]',
        ],
        "Sinusoidal": ["PROJ", '"SINUSOIDAL"'],
        "Robinson": ["PROJ", '"ROBINSON"'],
        "Mollweide": ["PROJ", '"MOLLWEIDE"'],
        "Transverse Mercator": ["EPSG", 9807],
        "Lambert Conic Conformal (2SP)": ["EPSG", 9802],
        "Polar Stereographic (variant A)": ["EPSG", 9810],
        "Lambert Azimuthal Equal Area": ["EPSG", 9820],
        "Albers Equal Area": ["EPSG", 9822],
        "Orthographic": ["EPSG", 9840],
        "Popular Visualisation Pseudo Mercator": ["EPSG", 1024],
    }

    TEMPLATE_OCENTRIC_SPHERE = """PROJCRS["$projection_name",
    BASEGEOGCRS["$name ($version) $reference",
        $datum,
        ID["IAU", $number_body, $version]],
    $conversion
    CS[Cartesian, 2],
        AXIS["$direction_name", $direction,
            ORDER[1],
            LENGTHUNIT["metre", 1]],
        AXIS["Northing (N)", north,
            ORDER[2],
            LENGTHUNIT["metre", 1]],
    ID["IAU", $number, $version]]"""

    TEMPLATE_OCENTRIC = """PROJCRS["$projection_name",
    BASEGEODCRS["$name ($version) $reference",
        $datum,
        ID["IAU", $number_body, $version]],
    $conversion
    CS[Cartesian, 2],
        AXIS["$direction_name", $direction,
            ORDER[1],
            LENGTHUNIT["metre", 1]],
        AXIS["Northing (N)", north,
            ORDER[2],
            LENGTHUNIT["metre", 1]],
    ID["IAU", $number, $version]]"""

    TEMPLATE_OGRAPHIC = """PROJCRS["$projection_name",
    BASEGEOGCRS["$name ($version) $reference",
        $datum,
        ID["IAU", $number_body, $version]],
    $conversion
    CS[Cartesian, 2],
        AXIS["$direction_name", $direction,
            ORDER[1],
            LENGTHUNIT["metre", 1]],
        AXIS["Northing (N)", north,
            ORDER[2],
            LENGTHUNIT["metre", 1]],
    ID["IAU", $number, $version]]"""

    def __init__(
        self, body_crs: BodyCrs, projection: List[str], template: str
    ) -> None:
        """Creates the projected body.

        Args:
            body_crs (BodyCrs): Coordinate Reference System of the body
            projection (List[str]): projection elements
        """
        self.__body_crs: BodyCrs = body_crs
        self.__projection: List[str] = projection
        self.__template: str = template
        self.__conversion: Conversion = self._create_conversion(
            projection[1], projection[2], "METHOD", projection
        )

    def _create_conversion(  # pylint: disable=no-self-use
        self,
        conversion_name: str,
        method_name: str,
        method_id: str,
        projection: List[str],
    ) -> Conversion:
        """Create the conversion.

        Args:
            conversion_name (str): conversion name
            method_name (str): method name
            method_id (str): method ID
            projection (List[str]): projection elements

        Returns:
            Conversion: Coversion
        """
        return Conversion(conversion_name, method_name, method_id, projection)

    def _create_projection(self) -> str:
        """Returns the projection name.

        Returns:
            str: the projection name
        """
        projection: str = (
            f"{self.body_crs.datum.body.name} ({IAU_REPORT.VERSION}) "
        )
        if (
            self.body_crs.crs_type == CrsType.OCENTRIC
            and self.body_crs.datum.body.shape == ReferenceShape.SPHERE
        ):
            reference = (
                projection
                + "- "
                + self.body_crs.datum.body.shape.value
                + f" / {self.projection[1]}"
            )
        else:
            reference = (
                projection
                + "/ "
                + self.body_crs.crs_type.value
                + f" / {self.projection[1]}"
            )
        return reference

    def _create_reference(self) -> str:
        """Returns the reference name.

        Returns:
            str: the reference name
        """
        reference: str
        if (
            self.body_crs.crs_type == CrsType.OCENTRIC
            and self.body_crs.datum.body.shape == ReferenceShape.SPHERE
        ):
            reference = "- " + self.body_crs.datum.body.shape.value
        else:
            reference = "/ " + self.body_crs.crs_type.value
        return reference

    @property
    def body_crs(self) -> BodyCrs:
        """Returns the body description.

        Returns:
            str: the body description
        """
        return self.__body_crs

    @property
    def projection(self) -> List[str]:
        """Returns the projection elements.

        Returns:
            str: the projection elements
        """
        return self.__projection

    @property
    def template(self) -> str:
        """Returns the template.

        Returns:
            str: the template
        """
        return self.__template

    @property
    def iau_code(self) -> int:
        """Returns the IAU code.

        Returns:
            int: the IAU code
        """
        return self.body_crs.iau_code + int(self.projection[0])

    @property
    def datum(self) -> Datum:
        """Datum.

        :getter: Returns the datum
        :type: Datum
        """
        return self.body_crs.datum

    @staticmethod
    def create(body_crs: BodyCrs, projection: List[str]) -> "ProjectionBody":
        """Create a projected coordinate reference system.

        Args:
            body_crs (BodyCrs): body CRS description
            projection (List[str]): projection elements

        Raises:
            ValueError: Unknown CRS type

        Returns:
            ProjectionBody: projected CRS description
        """
        result: ProjectionBody
        if (
            body_crs.crs_type == CrsType.OCENTRIC
            and body_crs.datum.body.shape == ReferenceShape.SPHERE
        ):
            result = ProjectionBody(
                body_crs, projection, ProjectionBody.TEMPLATE_OCENTRIC_SPHERE
            )
        elif body_crs.crs_type == CrsType.OCENTRIC:
            result = ProjectionBody(
                body_crs, projection, ProjectionBody.TEMPLATE_OCENTRIC
            )
        elif body_crs.crs_type == CrsType.OGRAPHIC:
            result = ProjectionBody(
                body_crs, projection, ProjectionBody.TEMPLATE_OGRAPHIC
            )
        else:
            raise ValueError(f"Unknown CRS type: {CrsType}")
        return result

    def wkt(self) -> str:
        """Returns the WKT of the projected body.

        Returns:
            str: the WKT of the projected body
        """
        proj_body_template = Template(self.template)
        return proj_body_template.substitute(
            projection_name=self._create_projection(),
            name=self.body_crs.name,
            version=IAU_REPORT.VERSION,
            datum=self.body_crs.datum.wkt(),
            number=self.body_crs.iau_code + int(self.projection[0]),
            number_body=self.body_crs.iau_code,
            conversion=self.__conversion.wkt(),
            reference=self._create_reference(),
            direction=self.body_crs.direction,
            direction_name="Westing (W)"
            if self.body_crs.direction == "west"
            else "Easting (E)",
        )

    @staticmethod
    def iter_projection(body_crs: BodyCrs) -> Generator:
        """Iter on the different projections of the projected body

        Args:
            body_crs (BodyCrs): Body to project

        Yields:
            Generator: Iterator of the projections of the body.
        """
        for projection in ProjectionBody.PROJECTION_DATA:
            yield ProjectionBody.create(body_crs, cast(List[str], projection))
