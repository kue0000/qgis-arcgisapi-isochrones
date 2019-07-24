import requests, json
from datetime import datetime, timedelta
from osgeo import ogr
from PyQt5.QtCore import QCoreApplication, QVariant
from qgis.core import (QgsProcessing,
                       QgsFeatureSink,
                       QgsProcessingException,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterEnum,
                       QgsProcessingParameterString,
                       QgsCoordinateReferenceSystem,
                       QgsProject,
                       QgsFeature,
                       QgsFields,
                       QgsField,
                       QgsCoordinateTransform,
                       QgsPolygon,
                       QgsLineString,
                       QgsPoint,
                       QgsGeometry)
import processing



class ArcGisIsochronesAlgorithm(QgsProcessingAlgorithm):

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    SOLVE_SERVICE_AREA_URL = 'https://route.arcgis.com/arcgis/rest/services/World/ServiceAreas/NAServer/ServiceArea_World'

    CLIENT_ID = 'YOURCLIENTID'
    CLIENT_SECRET = 'YOURCLIENTSECRET'
    
    CRS = QgsCoordinateReferenceSystem('EPSG:4326')

    INPUT = 'INPUT'
    OUTPUT_POLY = 'OUTPUT_POLY'
    OUTPUT_LINE = 'OUTPUT_LINE'
    MODE = 'MODE'
    THRESHOLDS = 'THRESHOLDS'

    def tr(self, string):
        """
        Returns a translatable string with the self.tr() function.
        """
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return ArcGisIsochronesAlgorithm()

    def name(self):
        """
        Returns the algorithm name, used for identifying the algorithm. This
        string should be fixed for the algorithm, and must not be localised.
        The name should be unique within each provider. Names should contain
        lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return 'arcgisisochrones'

    def displayName(self):
        """
        Returns the translated algorithm name, which should be used for any
        user-visible display of the algorithm name.
        """
        return self.tr('ArcGis Isochrones')

    def group(self):
        """
        Returns the name of the group this algorithm belongs to. This string
        should be localised.
        """
        return self.tr('MLM')

    def groupId(self):
        """
        Returns the unique ID of the group this algorithm belongs to. This
        string should be fixed for the algorithm, and must not be localised.
        The group id should be unique within each provider. Group id should
        contain lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return 'mlm'

    def shortHelpString(self):
        """
        Returns a localised short helper string for the algorithm. This string
        should provide a basic description about what the algorithm does and the
        parameters and outputs associated with it..
        """
        return self.tr("""Implements ESRI's 'Solve Service Area' API service to create isochrone polygons and lines
            Parameters:
            Mode: Set the mode of travel
            Thresholds: Set the isochrone thresholds (separated by commas) in kilometres if the mode calculates distance or in minutes if the mode calculates time e.g. \"1,2\" is either 1km & 2km or 1 minute & 2 minutes""")

    def initAlgorithm(self, config=None):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """

        self.token = self.get_token(self.CLIENT_ID, self.CLIENT_SECRET)

        # We add the input vector features source. It can have any kind of
        # geometry.
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                self.tr('Input layer (Point)'),
                [QgsProcessing.TypeVectorPoint]
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                self.MODE,
                self.tr('Mode'),
                self.get_travel_modes(self.token)
            )
        )

        self.addParameter(
            QgsProcessingParameterString(
                self.THRESHOLDS,
                self.tr('Thresholds')
            )
        )       

        # We add a feature sink in which to store our processed features (this
        # usually takes the form of a newly created vector layer when the
        # algorithm is run in QGIS).
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_POLY,
                self.tr('Isochrones - Polygons')
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_LINE,
                self.tr('Isochrones - Lines')
            )
        )
        
    def transform_wgs(self, pointXY, pointCRS):
        transform = QgsCoordinateTransform(pointCRS, self.CRS, QgsProject.instance())
        return transform.transform(pointXY)
        
    def get_token(self, client_id, client_secret):
        data = {
            'f': 'json',
            'client_id': client_id,
            'client_secret': client_secret,
            'grant_type': 'client_credentials'
        }
        url = 'https://www.arcgis.com/sharing/rest/oauth2/token'
        r = requests.post(url, data=data)
        return r.json()['access_token']

    def time_of_day(self, time):
        _ = list(map(int, time.split(':')))
        time_seconds = _[0]*60 + _[1]
        today = datetime.today().replace(hour=_[0], minute=_[1])
        epoch_time = today - datetime(1970, 1, 1)
        return 'timeOfDay=' + str(epoch_time.total_seconds())

    def travel_direction(self, direction='from'):
        if direction == 'to':
            return 'travelDirection=esriNATravelDirectionToFacility'
        return {'travelDirection': 'esriNATravelDirectionFromFacility'}

    def get_travel_modes(self, token):
        url = self.SOLVE_SERVICE_AREA_URL + '/retrieveTravelModes'
        data = {'f': 'pjson', 'token': token}
        r = requests.post(url, data=data)
        self.modes = r.json()
        return [i['name'] for i in self.modes['supportedTravelModes']]

    def travel_mode_names(self, modes):
        return [(i['name'], i['id'], i['impedanceAttributeName']) for i in modes['supportedTravelModes']]

    def service_area_polygons(self, ptype='detailed'):
        ptypes = {
            'none': 'esriNAOutputPolygonNone',
            'simple': 'esriNAOutputPolygonSimplified',
            'detailed': 'esriNAOutputPolygonDetailed'
        }
        return {'outputPolygons': ptypes.get(ptype), 'splitPolygonsAtBreaks': True}

    def service_area_lines(self, ltype='measure'):
        ltypes = {
            'none': 'esriNAOutputLineNone',
            'true': 'esriNAOutputLineTrueShape',
            'measure': 'esriNAOutputLineTrueShapeWithMeasure'
        }
        return {
            'outputLines': ltypes.get(ltype), 
            'splitLinesAtBreaks': True
        }

    def default_options(self):
        return {
            **self.service_area_polygons(),
            **self.service_area_lines(),
            **self.travel_direction()
            }

    def isochrone(self, lon, lat, token, breaks=None, mode=None, options=None):
        if not options:
            options = self.default_options()

        body = {
            'facilities': ','.join([str(lon), str(lat)]),
            'f': 'pjson',
            'token': token
        }
        for k, v in options.items():
            body[k] = v

        if breaks:
            body['defaultBreaks'] = str(breaks)

        if mode:
            body['travelMode'] = json.dumps(mode)

        url = self.SOLVE_SERVICE_AREA_URL + '/solveServiceArea'
        r = requests.post(url, data=body)
        try:
            return r.json()
        except:
            return str(r.content)

    def to_geojson(self, result):
        polygons = result.get('saPolygons')
        lines = result.get('saPolylines')
        features = []
        if polygons:
            for i in polygons['features']:
                f = {'type': 'Feature'}
                f['properties'] = i['attributes']
                f['geometry'] = {'type': 'Polygon', 'coordinates': i['geometry']['rings']}
                features.append(f)
        if lines:
            for i in lines['features']:
                f = {'type': 'Feature'}
                f['properties'] = i['attributes']
                f['geometry'] = {'type': 'MultiLineString', 'coordinates': i['geometry']['paths']}
                features.append(f)
        return {'type': 'FeatureCollection', 'features': features}

    def create_feature(self, json_feature):
        attrs = json_feature['attributes']
        geom = json_feature['geometry']
        f = QgsFeature()
        
        # add attributes to feature
        fields = QgsFields()
        for k, v in attrs.items():
            field_type = QVariant.String
            if type(v) == int:
                field_type = QVariant.Int
            elif type(v) in (str, type(None)):
                field_type = QVariant.String
            elif type(v) == float:
                field_type = QVariant.Double
            fields.append(QgsField(k, field_type))
        f.setFields(fields)
        
        for k, v in attrs.items():
            f[k] = v
            
        # add geometry to feature
        if 'paths' in geom.keys():
            x = [i[0] for i in geom['paths'][0]]
            y = [i[1] for i in geom['paths'][0]]
            z = [i[2] for i in geom['paths'][0]]
            g = QgsLineString(x, y, z)
        elif 'rings' in geom.keys():
            ogr_geometry = ogr.CreateGeometryFromJson(json.dumps({'type': 'Polygon', 'coordinates': geom['rings']}))
            g = QgsGeometry().fromWkt(ogr_geometry.ExportToWkt())
        f.setGeometry(g)
        return f
            
        
        
    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """

        source = self.parameterAsSource(
            parameters,
            self.INPUT,
            context
        )

        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))

        # Send some information to the user
        feedback.pushInfo('CRS is {}'.format(source.sourceCrs().authid()))

        # Compute the number of steps to display within the progress bar and
        # get features from source
        total = 100.0 / source.featureCount() if source.featureCount() else 0
        
        # token = self.get_token(self.CLIENT_ID, self.CLIENT_SECRET)
        features = source.getFeatures()
        output_polygons = []
        output_lines = []

        for current, feature in enumerate(features):
            # Stop the algorithm if cancel button has been clicked
            if feedback.isCanceled():
                break
            
            point = self.transform_wgs(feature.geometry().asPoint(), source.sourceCrs())
            mode = self.modes['supportedTravelModes'][int(self.parameterAsString(parameters, self.MODE, context))]
            feedback.pushInfo('mode: {}'.format(mode['name']))
            breaks = list(map(int,self.parameterAsString(parameters, self.THRESHOLDS, context).split(',')))

            feedback.pushInfo('Getting Isochrones for Point {}, {}'.format(point.x(), point.y()))
            feedback.pushInfo('Thresholds: {}'.format(breaks))
            res = self.isochrone(point.x(), point.y(), self.token, breaks=breaks, mode=mode)

            if type(res) == str:
                feedback.pushInfo('Error in the ArcGis response!')
                raise Exception
            
            feedback.pushInfo('Got Isochrones')
            feedback.pushInfo('Extracting features')


            for i in res['saPolygons']['features']:
                output_polygons.append(self.create_feature(i))

            for i in res['saPolylines']['features']:
                output_lines.append(self.create_feature(i))


            feedback.setProgress(int(current * total))
        feedback.pushInfo('All features extracted')
        
        feedback.pushInfo('Creating output layers')
        (sink_poly, dest_id_poly) = self.parameterAsSink(
            parameters,
            self.OUTPUT_POLY,
            context,
            output_polygons[0].fields(),
            output_polygons[0].geometry().wkbType(),
            self.CRS
        )

        (sink_line, dest_id_line) = self.parameterAsSink(
            parameters,
            self.OUTPUT_LINE,
            context,
            output_lines[0].fields(),
            output_lines[0].geometry().wkbType(),
            self.CRS
        )
        
        if sink_poly is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT_POLY))
        if sink_line is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT_LINE))
        
        sink_poly.addFeatures(output_polygons)
        sink_line.addFeatures(output_lines)
        
        return {self.OUTPUT_POLY: dest_id_poly, self.OUTPUT_LINE: dest_id_line}
